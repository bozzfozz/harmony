"""Background worker responsible for fetching and embedding artwork."""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.core.plex_client import PlexClient
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.db import session_scope
from app.logging import get_logger
from app.models import Download
from app.utils.artwork_utils import download_artwork, embed_artwork

logger = get_logger(__name__)


@dataclass(slots=True)
class ArtworkJob:
    download_id: Optional[int]
    file_path: str
    metadata: Dict[str, Any]
    spotify_track_id: Optional[str]
    artwork_url: Optional[str]


class ArtworkWorker:
    """Download high-resolution artwork and embed it into media files."""

    def __init__(
        self,
        spotify_client: SpotifyClient | None = None,
        plex_client: PlexClient | None = None,
        soulseek_client: SoulseekClient | None = None,
    ) -> None:
        self._spotify = spotify_client
        self._plex = plex_client
        self._soulseek = soulseek_client
        self._queue: asyncio.Queue[Optional[ArtworkJob]] = asyncio.Queue()
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

    async def wait_for_pending(self) -> None:
        await self._queue.join()

    async def enqueue(
        self,
        download_id: int | None,
        file_path: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        spotify_track_id: str | None = None,
        artwork_url: str | None = None,
    ) -> None:
        job = ArtworkJob(
            download_id=int(download_id) if download_id is not None else None,
            file_path=str(file_path),
            metadata=dict(metadata or {}),
            spotify_track_id=spotify_track_id,
            artwork_url=artwork_url,
        )
        if not self._running:
            await self._process_job(job)
            return
        await self._queue.put(job)

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            try:
                await self._process_job(job)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Artwork job failed: %s", exc)
            finally:
                self._queue.task_done()

    async def _process_job(self, job: ArtworkJob) -> None:
        download_id = job.download_id
        if download_id is not None:
            self._update_download(download_id, status="pending", path=None)

        try:
            artwork_path = await self._handle_job(job)
        except Exception as exc:
            if download_id is not None:
                self._update_download(download_id, status="failed", path=None)
            logger.debug("Artwork processing failed for %s: %s", download_id, exc)
            return

        if download_id is not None:
            self._update_download(download_id, status="done", path=str(artwork_path))

    async def _handle_job(self, job: ArtworkJob) -> Path:
        audio_path = Path(job.file_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        candidates = await self._collect_candidate_urls(job)
        artwork_file: Path | None = None
        for url in candidates:
            try:
                artwork_file = await asyncio.to_thread(download_artwork, url)
            except Exception:
                continue
            if artwork_file.exists():
                break

        if artwork_file is None or not artwork_file.exists():
            raise ValueError("Unable to retrieve artwork image")

        target = self._store_artwork(audio_path, artwork_file)
        await asyncio.to_thread(embed_artwork, audio_path, target)
        return target

    async def _collect_candidate_urls(self, job: ArtworkJob) -> list[str]:
        urls: list[str] = []

        spotify_url = await asyncio.to_thread(self._get_spotify_artwork_url, job.spotify_track_id)
        if spotify_url:
            urls.append(spotify_url)

        metadata_url = self._extract_metadata_artwork(job.metadata)
        if metadata_url and metadata_url not in urls:
            urls.append(metadata_url)

        if job.artwork_url and job.artwork_url not in urls:
            urls.append(job.artwork_url)

        urls.extend(self._extract_additional_urls(job.metadata))

        # Deduplicate whilst preserving order.
        seen: set[str] = set()
        unique_urls: list[str] = []
        for url in urls:
            if not url or url in seen:
                continue
            seen.add(url)
            unique_urls.append(url)
        return unique_urls

    def _get_spotify_artwork_url(self, track_id: str | None) -> Optional[str]:
        if not track_id or self._spotify is None:
            return None
        try:
            track = self._spotify.get_track_details(track_id)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Spotify lookup failed for %s: %s", track_id, exc)
            return None
        if not isinstance(track, Mapping):
            return None

        album = track.get("album")
        if isinstance(album, Mapping):
            url = self._pick_best_image(album.get("images"))
            if url:
                return url

        # Some Spotify payloads return images at the top level.
        url = self._pick_best_image(track.get("images"))
        if url:
            return url

        return None

    def _extract_metadata_artwork(self, metadata: Mapping[str, Any]) -> Optional[str]:
        keys = (
            "artwork_url",
            "cover_url",
            "image_url",
            "thumbnail",
            "thumb",
        )
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        album = metadata.get("album")
        if isinstance(album, Mapping):
            url = self._pick_best_image(album.get("images"))
            if url:
                return url
        return None

    def _extract_additional_urls(self, metadata: Mapping[str, Any]) -> list[str]:
        urls: list[str] = []
        candidates = metadata.get("artwork_urls")
        if isinstance(candidates, list):
            for entry in candidates:
                if isinstance(entry, str) and entry.strip():
                    urls.append(entry.strip())
                elif isinstance(entry, Mapping):
                    url = entry.get("url")
                    if isinstance(url, str) and url.strip():
                        urls.append(url.strip())

        # Plex metadata can expose an absolute URL via the thumb key.
        plex_thumb = metadata.get("plex_thumb") or metadata.get("plex_artwork")
        if isinstance(plex_thumb, str) and plex_thumb.strip():
            urls.append(plex_thumb.strip())

        soulseek_url = metadata.get("soulseek_artwork")
        if isinstance(soulseek_url, str) and soulseek_url.strip():
            urls.append(soulseek_url.strip())

        return urls

    @staticmethod
    def _pick_best_image(images: Any) -> Optional[str]:
        if not isinstance(images, list):
            return None
        best_url: Optional[str] = None
        best_score = -1
        for item in images:
            if not isinstance(item, Mapping):
                continue
            url = item.get("url")
            if not url:
                continue
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            score = width * height
            if score > best_score:
                best_score = score
                best_url = str(url)
        return best_url

    @staticmethod
    def _store_artwork(audio_path: Path, artwork_path: Path) -> Path:
        target_dir = audio_path.parent
        suffix = artwork_path.suffix or ".jpg"
        target = target_dir / f"cover{suffix}"
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            if target.exists():
                target.unlink()
        except OSError:  # pragma: no cover - defensive cleanup
            logger.debug("Unable to remove existing artwork at %s", target)
        shutil.move(str(artwork_path), target)
        return target

    def _update_download(self, download_id: int, *, status: str, path: str | None) -> None:
        with session_scope() as session:
            download = session.get(Download, int(download_id))
            if download is None:
                return
            download.artwork_status = status
            download.artwork_path = path
            download.updated_at = datetime.utcnow()
            session.add(download)

