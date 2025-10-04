"""Background worker responsible for fetching and embedding artwork."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, Mapping, Optional, Sequence, cast
from urllib.parse import urlparse

from app.config import ArtworkConfig, ArtworkPostProcessingConfig, load_config
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
    cache_key: Optional[str] = None
    refresh: bool = False


@dataclass(slots=True)
class DownloadContext:
    id: int
    filename: str
    spotify_track_id: Optional[str]
    spotify_album_id: Optional[str]
    request_payload: Mapping[str, Any] | None
    artwork_path: Optional[str]
    has_artwork: bool


@dataclass(slots=True)
class ArtworkProcessingResult:
    status: str
    artwork_path: Path | None
    replaced: bool
    was_low_res: bool
    has_artwork: bool


PostProcessingHook = Callable[[ArtworkJob, ArtworkProcessingResult], Awaitable[None] | None]


class ArtworkWorker:
    """Download high-resolution artwork and embed it into media files."""

    def __init__(
        self,
        spotify_client: SpotifyClient | None = None,
        soulseek_client: SoulseekClient | None = None,
        *,
        storage_directory: Path | None = None,
        config: ArtworkConfig | None = None,
        post_processing_hooks: Sequence[PostProcessingHook] | None = None,
        post_processing_enabled: bool | None = None,
    ) -> None:
        self._spotify = spotify_client
        self._soulseek = soulseek_client
        artwork_utils.SPOTIFY_CLIENT = spotify_client

        if config is None:
            config = load_config().artwork

        if storage_directory is not None:
            base_dir = Path(storage_directory)
        else:
            base_dir = Path(config.directory or (os.getenv("ARTWORK_DIR") or "./artwork"))

        self._storage_dir = base_dir.expanduser().resolve()
        self._timeout = float(config.timeout_seconds)
        self._max_bytes = int(config.max_bytes)
        self._concurrency = max(1, int(config.concurrency))
        self._min_edge = max(1, int(config.min_edge))
        self._min_bytes = max(1, int(config.min_bytes))
        fallback_provider = (config.fallback.provider or "").strip().lower()
        self._fallback_enabled = config.fallback.enabled and fallback_provider not in {"", "none"}
        self._fallback_provider = fallback_provider or "musicbrainz"
        self._fallback_timeout = float(config.fallback.timeout_seconds)
        self._fallback_max_bytes = int(config.fallback.max_bytes)

        post_processing_config: ArtworkPostProcessingConfig = getattr(
            config, "post_processing", ArtworkPostProcessingConfig()
        )
        if post_processing_enabled is None:
            self._post_processing_enabled = bool(post_processing_config.enabled)
        else:
            self._post_processing_enabled = bool(post_processing_enabled)

        self._post_processing_hooks: list[PostProcessingHook] = []
        if self._post_processing_enabled and post_processing_config.hooks:
            self._post_processing_hooks.extend(
                self._import_post_processors(post_processing_config.hooks)
            )
        if post_processing_hooks:
            self._post_processing_hooks.extend(post_processing_hooks)

        self._queue: asyncio.Queue[Optional[ArtworkJob]] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._workers = [asyncio.create_task(self._worker_loop()) for _ in range(self._concurrency)]

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for _ in range(len(self._workers)):
            await self._queue.put(None)
        for task in self._workers:
            try:
                await task
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Artwork worker task failed during shutdown")
        self._workers.clear()

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
        refresh: bool = False,
    ) -> None:
        job = ArtworkJob(
            download_id=int(download_id) if download_id is not None else None,
            file_path=str(file_path),
            metadata=dict(metadata or {}),
            spotify_track_id=spotify_track_id,
            spotify_album_id=spotify_album_id,
            artwork_url=artwork_url,
            refresh=bool(refresh),
        )
        if not self._running:
            await self._process_job(job)
            return
        await self._queue.put(job)

    async def _worker_loop(self) -> None:
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
                        artwork_path=record.artwork_path,
                        has_artwork=bool(record.has_artwork),
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
                has_artwork=False,
            )

        start_time = time.monotonic()
        try:
            result = await self._handle_job(job, download_context)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            if download_id is not None:
                self._update_download(
                    download_id,
                    status="failed",
                    path=None,
                    spotify_track_id=job.spotify_track_id,
                    spotify_album_id=job.spotify_album_id,
                    has_artwork=False,
                )
            logger.info(
                "Artwork processing failed",
                extra={
                    "event": "artwork_fetch",
                    "download_id": download_id,
                    "album_id": job.spotify_album_id or job.cache_key,
                    "status": "failed",
                    "duration_ms": duration_ms,
                    "was_low_res": None,
                    "refresh": job.refresh,
                },
            )
            logger.debug("Artwork processing exception: %s", exc)
            return

        duration_ms = int((time.monotonic() - start_time) * 1000)
        stored_path: Optional[str] = None
        if result.artwork_path is not None:
            stored_path = str(result.artwork_path)
        elif download_context and download_context.artwork_path:
            stored_path = download_context.artwork_path

        if download_id is not None:
            self._update_download(
                download_id,
                status="done",
                path=stored_path,
                spotify_track_id=job.spotify_track_id,
                spotify_album_id=job.spotify_album_id,
                artwork_url=job.artwork_url,
                has_artwork=result.has_artwork,
            )

        outcome = (
            "replaced"
            if result.replaced
            else ("embedded" if result.status != "skipped" else "skipped")
        )

        logger.info(
            "Artwork processing completed",
            extra={
                "event": "artwork_replace",
                "download_id": download_id,
                "album_id": job.spotify_album_id or job.cache_key,
                "result": outcome,
                "duration_ms": duration_ms,
                "was_low_res": result.was_low_res,
                "refresh": job.refresh,
            },
        )

    async def _handle_job(
        self,
        job: ArtworkJob,
        download: DownloadContext | None,
    ) -> ArtworkProcessingResult:
        audio_path = Path(job.file_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        existing_artwork_path: Path | None = None
        if download and download.artwork_path:
            existing_artwork_path = Path(download.artwork_path)

        existing_info = await asyncio.to_thread(artwork_utils.extract_embed_info, audio_path)
        has_existing = existing_info is not None
        was_low_res = bool(
            existing_info
            and artwork_utils.is_low_res(
                existing_info,
                self._min_edge,
                self._min_bytes,
            )
        )

        should_replace = job.refresh or not has_existing or was_low_res

        if not should_replace:
            return ArtworkProcessingResult(
                status="skipped",
                artwork_path=existing_artwork_path,
                replaced=False,
                was_low_res=False,
                has_artwork=has_existing or bool(existing_artwork_path),
            )

        candidates = await self._collect_candidate_urls(job, download)
        if not candidates:
            raise ValueError("No artwork sources available")

        target_base = self._storage_dir / self._generate_storage_name(job, audio_path)
        artwork_file: Path | None = None

        cached_file = None if job.refresh else self._find_cached_artwork(target_base)
        if cached_file is not None:
            logger.info(
                "Artwork cache hit",
                extra={
                    "event": "artwork_cache_hit",
                    "download_id": job.download_id,
                    "album_id": job.spotify_album_id or job.cache_key,
                    "status": "hit",
                },
            )
            artwork_file = cached_file
        else:
            for url in candidates:
                try:
                    timeout = self._timeout
                    max_bytes = self._max_bytes
                    allowed_hosts: Sequence[str] | None = None
                    if artwork_utils.allowed_remote_host(
                        url, allowed_hosts=artwork_utils.FALLBACK_HOST_ALLOWLIST
                    ):
                        allowed_hosts = artwork_utils.FALLBACK_HOST_ALLOWLIST
                        timeout = self._fallback_timeout
                        max_bytes = self._fallback_max_bytes

                    artwork_file = await asyncio.to_thread(
                        artwork_utils.download_artwork,
                        url,
                        target_base,
                        timeout=timeout,
                        max_bytes=max_bytes,
                        allowed_hosts=allowed_hosts,
                    )
                except Exception as exc:  # pragma: no cover - network/IO failures
                    logger.debug("Artwork download failed from %s: %s", url, exc)
                    continue

                job.artwork_url = url
                break

        if artwork_file is None or not artwork_file.exists():
            raise ValueError("Unable to retrieve artwork image")

        await asyncio.to_thread(artwork_utils.embed_artwork, audio_path, artwork_file)
        logger.info(
            "Embedded artwork into file",
            extra={
                "event": "artwork_embed",
                "download_id": job.download_id,
                "album_id": job.spotify_album_id or job.cache_key,
                "source_url": job.artwork_url,
            },
        )

        result = ArtworkProcessingResult(
            status="done",
            artwork_path=artwork_file,
            replaced=has_existing,
            was_low_res=was_low_res,
            has_artwork=True,
        )
        await self._run_post_processing_hooks(job, result)
        return result

    def register_post_processor(self, hook: PostProcessingHook) -> None:
        self._post_processing_hooks.append(hook)

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
            job.cache_key = job.cache_key or album_id
            spotify_album_url = await asyncio.to_thread(
                artwork_utils.fetch_spotify_artwork,
                album_id,
            )
            if spotify_album_url:
                urls.append(spotify_album_url)

        spotify_url = await asyncio.to_thread(
            self._get_spotify_artwork_url,
            job.spotify_track_id,
        )
        if spotify_url and spotify_url not in urls:
            urls.append(spotify_url)

        metadata_url = self._extract_metadata_artwork(job.metadata)
        if metadata_url and metadata_url not in urls:
            urls.append(metadata_url)

        if job.artwork_url and job.artwork_url not in urls:
            urls.append(job.artwork_url)

        urls.extend(self._extract_additional_urls(job.metadata))

        if self._fallback_enabled and self._fallback_provider == "musicbrainz":
            artist, album = self._extract_artist_album(job, download)
            if artist and album:
                fallback_url = await asyncio.to_thread(
                    artwork_utils.fetch_caa_artwork,
                    artist,
                    album,
                    timeout=self._fallback_timeout,
                )
                if fallback_url:
                    job.cache_key = job.cache_key or self._extract_fallback_cache_key(fallback_url)
                    job.artwork_url = fallback_url
                    urls.append(fallback_url)
                    logger.info(
                        "Artwork fallback candidate resolved",
                        extra={
                            "event": "artwork_fetch",
                            "download_id": job.download_id,
                            "album_id": job.spotify_album_id or job.cache_key,
                            "status": "fallback",
                            "provider": "musicbrainz",
                        },
                    )

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
            artwork_path=download.artwork_path if download else None,
            has_artwork=bool(download.has_artwork) if download else False,
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
        candidate = job.cache_key or job.spotify_album_id or job.spotify_track_id or audio_path.stem
        if not candidate and job.download_id is not None:
            candidate = f"download-{job.download_id}"
        if not candidate:
            candidate = audio_path.stem or "artwork"
        slug = re.sub(r"[^a-zA-Z0-9._-]", "_", candidate)
        slug = slug.strip("_") or "artwork"
        if not slug.endswith("_original"):
            slug = f"{slug}_original"
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
        has_artwork: bool | None = None,
    ) -> None:
        with session_scope() as session:
            download = session.get(Download, int(download_id))
            if download is None:
                return
            download.artwork_status = status
            if path is not None:
                download.artwork_path = path
            elif status in {"failed", "pending"}:
                download.artwork_path = None
            if has_artwork is not None:
                download.has_artwork = has_artwork
            else:
                download.has_artwork = bool(download.artwork_path) and status == "done"
            if spotify_track_id:
                download.spotify_track_id = spotify_track_id
            if spotify_album_id:
                download.spotify_album_id = spotify_album_id
            if artwork_url:
                download.artwork_url = artwork_url
            download.updated_at = datetime.utcnow()
            session.add(download)

    def _extract_artist_album(
        self,
        job: ArtworkJob,
        download: DownloadContext | None,
    ) -> tuple[Optional[str], Optional[str]]:
        sources = list(self._collect_metadata_sources(job, download))
        artist = self._extract_text(
            ("artist", "artist_name", "artistName", "artists"),
            sources,
        )
        album = self._extract_text(
            ("album", "album_name", "albumName", "release"),
            sources,
        )
        return artist, album

    def _collect_metadata_sources(
        self,
        job: ArtworkJob,
        download: DownloadContext | None,
    ) -> Iterable[Mapping[str, Any]]:
        sources: list[Mapping[str, Any]] = []
        for payload in (job.metadata,):
            if isinstance(payload, Mapping) and payload not in sources:
                sources.append(payload)
                nested = payload.get("metadata")
                if isinstance(nested, Mapping):
                    sources.append(nested)

        if download and download.request_payload:
            payload = download.request_payload
            if isinstance(payload, Mapping) and payload not in sources:
                sources.append(payload)
                nested = payload.get("metadata")
                if isinstance(nested, Mapping):
                    sources.append(nested)

            track_payload = payload.get("track") if isinstance(payload, Mapping) else None
            if isinstance(track_payload, Mapping):
                sources.append(track_payload)

            file_payload = payload.get("file") if isinstance(payload, Mapping) else None
            if isinstance(file_payload, Mapping):
                sources.append(file_payload)

        return sources

    def _extract_text(
        self,
        keys: Sequence[str],
        sources: Iterable[Mapping[str, Any]],
    ) -> Optional[str]:
        for source in sources:
            for key in keys:
                if key not in source:
                    continue
                candidate = self._normalise_text(source[key])
                if candidate:
                    return candidate
        return None

    def _normalise_text(self, value: Any) -> Optional[str]:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            for key in ("name", "title", "value"):
                nested = value.get(key)
                candidate = self._normalise_text(nested)
                if candidate:
                    return candidate
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for entry in value:
                candidate = self._normalise_text(entry)
                if candidate:
                    return candidate
        return None

    def _extract_fallback_cache_key(self, url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
        except ValueError:
            return None
        segments = [segment for segment in parsed.path.split("/") if segment]
        for index, segment in enumerate(segments):
            if segment == "release-group" and index + 1 < len(segments):
                return segments[index + 1]
        return None

    async def _run_post_processing_hooks(
        self, job: ArtworkJob, result: ArtworkProcessingResult
    ) -> None:
        if (
            not self._post_processing_enabled
            or not self._post_processing_hooks
            or result.artwork_path is None
        ):
            return

        for hook in list(self._post_processing_hooks):
            try:
                outcome = hook(job, result)
                if inspect.isawaitable(outcome):
                    await cast(Awaitable[None], outcome)
            except Exception:
                logger.exception(
                    "Artwork post-processing hook failed",
                    extra={
                        "event": "artwork_post_process",
                        "download_id": job.download_id,
                        "hook": getattr(
                            hook,
                            "__qualname__",
                            getattr(hook, "__name__", repr(hook)),
                        ),
                    },
                )

    def _import_post_processors(
        self, dotted_paths: Sequence[str]
    ) -> list[PostProcessingHook]:
        hooks: list[PostProcessingHook] = []
        for path in dotted_paths:
            if not path:
                continue
            try:
                hooks.append(self._import_hook(path))
            except Exception:
                logger.exception(
                    "Failed to import artwork post-processing hook",
                    extra={"event": "artwork_post_process", "hook": path},
                )
        return hooks

    @staticmethod
    def _import_hook(path: str) -> PostProcessingHook:
        if not path:
            raise ValueError("Hook path must be non-empty")

        module_path: str
        attribute: str
        if ":" in path:
            module_path, attribute = path.split(":", 1)
        else:
            module_path, _, attribute = path.rpartition(".")
        if not module_path or not attribute:
            raise ValueError(f"Invalid hook path '{path}'")

        module = importlib.import_module(module_path)
        hook = getattr(module, attribute)
        if not callable(hook):
            raise TypeError(f"Hook '{path}' is not callable")
        return cast(PostProcessingHook, hook)
