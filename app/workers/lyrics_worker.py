"""Background worker that generates LRC lyric files for completed downloads."""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import quote

import httpx

from app.db import session_scope
from app.logging import get_logger
from app.models import Download
from app.utils.lyrics_utils import generate_lrc

logger = get_logger(__name__)

LyricsProvider = Callable[[Dict[str, Any]], Awaitable[Optional[str]] | Optional[str]]


@dataclass(slots=True)
class LyricsJob:
    download_id: Optional[int]
    file_path: str
    track_info: Dict[str, Any]


async def default_lyrics_provider(track_info: Dict[str, Any]) -> Optional[str]:
    """Fetch lyrics from the public lyrics.ovh API."""

    artist = str(track_info.get("artist") or track_info.get("artist_name") or "").strip()
    title = str(track_info.get("title") or track_info.get("name") or "").strip()
    if not artist or not title:
        return None

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"https://api.lyrics.ovh/v1/{quote(artist)}/{quote(title)}"
            )
        except httpx.HTTPError as exc:  # pragma: no cover - network failure
            logger.debug("Lyrics API request failed for %s - %s: %s", artist, title, exc)
            return None

    if response.status_code != 200:  # pragma: no cover - API error path
        logger.debug(
            "Lyrics API returned %s for %s - %s", response.status_code, artist, title
        )
        return None

    try:
        payload = response.json()
    except ValueError:  # pragma: no cover - invalid payload
        logger.debug("Lyrics API returned invalid JSON for %s - %s", artist, title)
        return None

    lyrics = payload.get("lyrics") if isinstance(payload, dict) else None
    if isinstance(lyrics, str) and lyrics.strip():
        return lyrics
    return None


class LyricsWorker:
    """Generate synchronised lyric files for completed downloads."""

    def __init__(
        self,
        lyrics_provider: LyricsProvider | None = None,
    ) -> None:
        self._provider = lyrics_provider or default_lyrics_provider
        self._queue: asyncio.Queue[Optional[LyricsJob]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._running = False

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
        track_info: Dict[str, Any],
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
            self._update_download(download_id, status="pending", path=None)

        try:
            lrc_path = await self._create_lrc(job)
        except Exception as exc:
            if download_id is not None:
                self._update_download(download_id, status="failed", path=None)
            logger.debug("Lyrics generation failed for %s: %s", download_id, exc)
            return

        if download_id is not None:
            self._update_download(download_id, status="done", path=str(lrc_path))

    async def _create_lrc(self, job: LyricsJob) -> Path:
        audio_path = Path(job.file_path)
        target = audio_path.with_suffix(".lrc")
        target.parent.mkdir(parents=True, exist_ok=True)

        lyrics = await self._obtain_lyrics(job.track_info)
        if not lyrics:
            raise ValueError("Lyrics provider returned no content")

        lrc_content = generate_lrc(job.track_info, lyrics)
        target.write_text(lrc_content, encoding="utf-8")
        return target

    async def _obtain_lyrics(self, track_info: Dict[str, Any]) -> Optional[str]:
        result = self._provider(track_info)
        if inspect.isawaitable(result):
            return await result  # type: ignore[return-value]
        return result

    def _update_download(self, download_id: int, *, status: str, path: str | None) -> None:
        with session_scope() as session:
            download = session.get(Download, int(download_id))
            if download is None:
                return
            download.lyrics_status = status
            download.lyrics_path = path
            download.updated_at = datetime.utcnow()
            session.add(download)

