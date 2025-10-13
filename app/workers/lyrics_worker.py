"""Background worker that generates LRC lyric files for completed downloads."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import inspect
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from app.core.spotify_client import SpotifyClient
from app.db import run_session
from app.logging import get_logger
from app.models import Download
from app.utils import lyrics_utils
from app.utils.lyrics_utils import convert_to_lrc, fetch_spotify_lyrics, save_lrc_file
from app.utils.path_safety import ensure_within_roots

logger = get_logger(__name__)

LyricsPayload = dict[str, Any]
LyricsProvider = Callable[[dict[str, Any]], Awaitable[LyricsPayload | None] | LyricsPayload | None]


@dataclass(slots=True)
class LyricsJob:
    download_id: int | None
    file_path: str
    track_info: dict[str, Any]


async def default_fallback_provider(
    track_info: Mapping[str, Any],
) -> LyricsPayload | None:
    """Fetch lyrics from Musixmatch or the public lyrics.ovh API."""

    musixmatch_payload = await lyrics_utils.fetch_musixmatch_subtitles(track_info)
    if musixmatch_payload:
        return musixmatch_payload

    artist = _resolve_text(track_info, ("artist", "artist_name", "artists"))
    title = _resolve_text(track_info, ("title", "name", "track"))
    if not artist or not title:
        return None

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"https://api.lyrics.ovh/v1/{quote(artist)}/{quote(title)}")
        except httpx.HTTPError as exc:  # pragma: no cover - network failure
            logger.debug("Lyrics API request failed for %s - %s: %s", artist, title, exc)
            return None

    if response.status_code != 200:  # pragma: no cover - API error path
        logger.debug("Lyrics API returned %s for %s - %s", response.status_code, artist, title)
        return None

    try:
        payload = response.json()
    except ValueError:  # pragma: no cover - invalid payload
        logger.debug("Lyrics API returned invalid JSON for %s - %s", artist, title)
        return None

    lyrics = payload.get("lyrics") if isinstance(payload, dict) else None
    if isinstance(lyrics, str) and lyrics.strip():
        return {
            "title": title,
            "artist": artist,
            "album": _resolve_text(track_info, ("album", "album_name", "release")),
            "lyrics": lyrics.strip(),
        }
    return None


class LyricsWorker:
    """Generate synchronised lyric files for completed downloads."""

    def __init__(
        self,
        *,
        spotify_client: SpotifyClient | None = None,
        fallback_provider: LyricsProvider | None = None,
        allowed_roots: Sequence[Path] | None = None,
    ) -> None:
        self._spotify = spotify_client
        lyrics_utils.SPOTIFY_CLIENT = spotify_client
        self._fallback = fallback_provider or default_fallback_provider
        self._queue: asyncio.Queue[LyricsJob | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        roots = [Path(path) for path in allowed_roots] if allowed_roots else []
        self._allowed_roots: tuple[Path, ...] = tuple(
            root.expanduser().resolve(strict=False) for root in roots
        )

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        await self._queue.put(None)
        if self._task is not None:
            try:
                await self._task
            finally:
                self._task = None

    async def enqueue(
        self,
        download_id: int | None,
        file_path: str,
        track_info: dict[str, Any],
    ) -> None:
        job = LyricsJob(download_id=download_id, file_path=file_path, track_info=dict(track_info))
        if not self._running:
            await self._process_job(job)
            return
        await self._queue.put(job)

    async def wait_for_pending(self) -> None:
        """Wait until all queued jobs have been processed."""

        await self._queue.join()

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            try:
                await self._process_job(job)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Lyrics job failed: %s", exc)
            finally:
                self._queue.task_done()

    async def _process_job(self, job: LyricsJob) -> None:
        download_id = job.download_id
        if download_id is not None:
            await self._update_download(download_id, status="pending", path=None)

        try:
            lrc_path = await self._create_lrc(job)
        except Exception as exc:
            if download_id is not None:
                await self._update_download(download_id, status="failed", path=None)
            logger.debug("Lyrics generation failed for %s: %s", download_id, exc)
            return

        if download_id is not None:
            await self._update_download(download_id, status="done", path=str(lrc_path))

    async def _create_lrc(self, job: LyricsJob) -> Path:
        audio_path = self._ensure_allowed_path(job.file_path)
        target = audio_path.with_suffix(".lrc")
        target = self._ensure_allowed_path(target)

        lyrics_payload = await self._obtain_lyrics(job.track_info)
        if not lyrics_payload:
            raise ValueError("Lyrics provider returned no content")

        combined: dict[str, Any] = dict(job.track_info)
        combined.update(lyrics_payload)

        lrc_content = convert_to_lrc(combined)
        save_lrc_file(target, lrc_content)
        return target

    async def _obtain_lyrics(self, track_info: dict[str, Any]) -> LyricsPayload | None:
        track_id = self._extract_spotify_id(track_info)
        if track_id:
            spotify_payload = await asyncio.to_thread(fetch_spotify_lyrics, track_id)
            if spotify_payload:
                return spotify_payload

        result = self._fallback(track_info)
        if inspect.isawaitable(result):
            result = await result  # type: ignore[assignment]

        if isinstance(result, Mapping):
            return dict(result)
        if isinstance(result, str):
            return {"lyrics": result}
        return None

    async def _update_download(self, download_id: int, *, status: str, path: str | None) -> None:
        def _apply(session: Session) -> None:
            download = session.get(Download, int(download_id))
            if download is None:
                return
            download.lyrics_status = status
            download.lyrics_path = path
            download.has_lyrics = bool(path and status == "done")
            download.updated_at = datetime.utcnow()
            session.add(download)

        await run_session(_apply)

    def _ensure_allowed_path(self, path: str | Path) -> Path:
        if not self._allowed_roots:
            return Path(path)
        return ensure_within_roots(path, allowed_roots=self._allowed_roots)

    @staticmethod
    def _extract_spotify_id(track_info: Mapping[str, Any]) -> str | None:
        keys = (
            "spotify_track_id",
            "spotifyTrackId",
            "spotify_id",
            "spotifyId",
            "id",
        )
        for key in keys:
            value = track_info.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, Mapping):
                nested = value.get("id")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
        return None


def _resolve_text(track_info: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = track_info.get(key)
        if isinstance(value, Mapping):
            nested = value.get("name")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, Mapping):
                nested = first.get("name")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
            if isinstance(first, str) and first.strip():
                return first.strip()
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


__all__ = ["LyricsWorker", "default_fallback_provider"]
