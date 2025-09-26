"""Background worker responsible for fetching and embedding artwork."""

from __future__ import annotations

import asyncio
import os
import re
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
from app.utils import artwork_utils

logger = get_logger(__name__)


@dataclass(slots=True)
class ArtworkJob:
    download_id: Optional[int]
    file_path: str
    metadata: Dict[str, Any]
    spotify_track_id: Optional[str]
    spotify_album_id: Optional[str]
    artwork_url: Optional[str]


@dataclass(slots=True)
class DownloadContext:
    id: int
    filename: str
    spotify_track_id: Optional[str]
    spotify_album_id: Optional[str]
    request_payload: Mapping[str, Any] | None


class ArtworkWorker:
    """Download high-resolution artwork and embed it into media files."""

    def __init__(
        self,
        spotify_client: SpotifyClient | None = None,
        plex_client: PlexClient | None = None,
        soulseek_client: SoulseekClient | None = None,
        *,
        storage_directory: Path | None = None,
    ) -> None:
        self._spotify = spotify_client
        self._plex = plex_client
        self._soulseek = soulseek_client
        artwork_utils.SPOTIFY_CLIENT = spotify_client
        self._queue: asyncio.Queue[Optional[ArtworkJob]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        base_dir = storage_directory
        if base_dir is None:
            env_dir = os.getenv("ARTWORK_DIR") or os.getenv("HARMONY_ARTWORK_DIR")
            base_dir = Path(env_dir) if env_dir else Path("./artwork")
        self._storage_dir = Path(base_dir).resolve()

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
        spotify_album_id: str | None = None,
        artwork_url: str | None = None,
    ) -> None:
        job = ArtworkJob(
            download_id=int(download_id) if download_id is not None else None,
            file_path=str(file_path),
            metadata=dict(metadata or {}),
            spotify_track_id=spotify_track_id,
            spotify_album_id=spotify_album_id,
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
        download_context: DownloadContext | None = None
        if download_id is not None:
            with session_scope() as session:
                record = session.get(Download, download_id)
                if record is not None:
                    payload = record.request_payload
                    payload_mapping = dict(payload) if isinstance(payload, Mapping) else None
                    download_context = DownloadContext(
                        id=record.id,
                        filename=record.filename,
                        spotify_track_id=record.spotify_track_id,
                        spotify_album_id=record.spotify_album_id,
                        request_payload=payload_mapping,
                    )
                    if not job.spotify_track_id and record.spotify_track_id:
                        job.spotify_track_id = record.spotify_track_id
                    if not job.spotify_album_id and record.spotify_album_id:
                        job.spotify_album_id = record.spotify_album_id
                    if not job.artwork_url and record.artwork_url:
                        job.artwork_url = record.artwork_url
        if download_id is not None:
            self._update_download(
                download_id,
                status="pending",
                path=None,
                spotify_track_id=job.spotify_track_id,
                spotify_album_id=job.spotify_album_id,
                artwork_url=job.artwork_url,
            )

        try:
            artwork_path = await self._handle_job(job, download_context)
        except Exception as exc:
            if download_id is not None:
                self._update_download(
                    download_id,
                    status="failed",
                    path=None,
                    spotify_track_id=job.spotify_track_id,
                    spotify_album_id=job.spotify_album_id,
                )
            logger.debug("Artwork processing failed for %s: %s", download_id, exc)
            return

        if download_id is not None:
            self._update_download(
                download_id,
                status="done",
                path=str(artwork_path),
                spotify_track_id=job.spotify_track_id,
                spotify_album_id=job.spotify_album_id,
                artwork_url=job.artwork_url,
            )

    async def _handle_job(
        self,
        job: ArtworkJob,
        download: DownloadContext | None,
    ) -> Path:
        audio_path = Path(job.file_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        candidates = await self._collect_candidate_urls(job, download)
        artwork_file: Path | None = None
        target_base = self._storage_dir / self._generate_storage_name(job, audio_path)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        cached_file = self._find_cached_artwork(target_base)
        if cached_file is not None:
            artwork_file = cached_file
        else:
            for url in candidates:
                try:
                    artwork_file = await asyncio.to_thread(
                        artwork_utils.download_artwork,
                        url,
                        target_base,
                    )
                except Exception:
                    continue
                if artwork_file.exists():
                    break

        if artwork_file is None or not artwork_file.exists():
            raise ValueError("Unable to retrieve artwork image")

        await asyncio.to_thread(artwork_utils.embed_artwork, audio_path, artwork_file)
        return artwork_file

    async def _collect_candidate_urls(
        self,
        job: ArtworkJob,
        download: DownloadContext | None,
    ) -> list[str]:
        urls: list[str] = []

        album_id = await asyncio.to_thread(
            self._resolve_spotify_album_id,
            job,
            download,
        )
        if album_id:
            job.spotify_album_id = job.spotify_album_id or album_id
            spotify_album_url = await asyncio.to_thread(
                artwork_utils.fetch_spotify_artwork,
                album_id,
            )
            if spotify_album_url:
                urls.append(spotify_album_url)

        spotify_url = await asyncio.to_thread(self._get_spotify_artwork_url, job.spotify_track_id)
        if spotify_url and spotify_url not in urls:
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

    def _resolve_spotify_album_id(
        self,
        job: ArtworkJob,
        download: DownloadContext | None,
    ) -> Optional[str]:
        if job.spotify_album_id:
            return job.spotify_album_id

        payload: Dict[str, Any] = {}
        if download is not None and download.request_payload:
            payload.update(download.request_payload)
        if job.metadata:
            existing_metadata = payload.get("metadata")
            if isinstance(existing_metadata, Mapping):
                combined = dict(existing_metadata)
                combined.update(job.metadata)
                payload["metadata"] = combined
            else:
                payload["metadata"] = dict(job.metadata)

        context = DownloadContext(
            id=download.id if download is not None else (job.download_id or 0),
            filename=job.file_path if job.file_path else (download.filename if download else ""),
            spotify_track_id=job.spotify_track_id
            or (download.spotify_track_id if download else None),
            spotify_album_id=download.spotify_album_id if download else None,
            request_payload=payload or None,
        )

        try:
            inferred = artwork_utils.infer_spotify_album_id(context)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Album inference failed for download %s: %s", context.id, exc)
        else:
            if inferred:
                return inferred

        metadata_album = job.metadata.get("album")
        if isinstance(metadata_album, Mapping):
            for key in ("spotify_id", "spotifyId", "id"):
                value = metadata_album.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        direct_id = job.metadata.get("spotify_album_id") or job.metadata.get("album_id")
        if isinstance(direct_id, str) and direct_id.strip():
            return direct_id.strip()

        if job.spotify_track_id and self._spotify is not None:
            try:
                track = self._spotify.get_track_details(job.spotify_track_id)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug(
                    "Failed to resolve album id for %s: %s",
                    job.spotify_track_id,
                    exc,
                )
            else:
                if isinstance(track, Mapping):
                    album = track.get("album")
                    if isinstance(album, Mapping):
                        candidate = album.get("id")
                        if isinstance(candidate, str) and candidate.strip():
                            return candidate.strip()

        return None

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

    def _generate_storage_name(self, job: ArtworkJob, audio_path: Path) -> str:
        candidate = job.spotify_album_id or job.spotify_track_id or audio_path.stem
        if not candidate and job.download_id is not None:
            candidate = f"download-{job.download_id}"
        if not candidate:
            candidate = audio_path.stem or "artwork"
        slug = re.sub(r"[^a-zA-Z0-9._-]", "_", candidate)
        slug = slug.strip("_") or "artwork"
        return slug

    def _find_cached_artwork(self, target_base: Path) -> Path | None:
        if target_base.exists() and target_base.is_file():
            return target_base

        candidates: list[Path] = []
        if target_base.suffix:
            candidates.append(target_base)
        else:
            for suffix in (".jpg", ".jpeg", ".png", ".webp"):
                candidates.append(target_base.with_suffix(suffix))

        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _update_download(
        self,
        download_id: int,
        *,
        status: str,
        path: str | None,
        spotify_track_id: str | None = None,
        spotify_album_id: str | None = None,
        artwork_url: str | None = None,
    ) -> None:
        with session_scope() as session:
            download = session.get(Download, int(download_id))
            if download is None:
                return
            download.artwork_status = status
            download.artwork_path = path
            download.has_artwork = bool(path) and status == "done"
            if spotify_track_id:
                download.spotify_track_id = spotify_track_id
            if spotify_album_id:
                download.spotify_album_id = spotify_album_id
            if artwork_url:
                download.artwork_url = artwork_url
            download.updated_at = datetime.utcnow()
            session.add(download)
