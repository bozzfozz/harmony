"""Background worker for processing Soulseek download jobs."""

from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from app.core.soulseek_client import SoulseekClient
from app.db import session_scope
from app.logging import get_logger
from app.models import Download
from app.utils.activity import (
    record_activity,
    record_worker_started,
    record_worker_stopped,
)
from app.utils.file_utils import organize_file
from app.utils.events import (
    DOWNLOAD_RETRY_COMPLETED,
    DOWNLOAD_RETRY_FAILED,
    DOWNLOAD_RETRY_SCHEDULED,
    WORKER_STOPPED,
)
from app.utils.settings_store import increment_counter, read_setting, write_setting
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat
from app.workers.artwork_worker import ArtworkWorker
from app.workers.lyrics_worker import LyricsWorker
from app.workers.metadata_worker import MetadataWorker
from app.workers.persistence import PersistentJobQueue, QueuedJob

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from app.workers.scan_worker import ScanWorker

logger = get_logger(__name__)

ALLOWED_STATES = {"queued", "downloading", "completed", "failed", "cancelled", "dead_letter"}

DEFAULT_CONCURRENCY = 2
DEFAULT_IDLE_POLL = 15.0

DEFAULT_MAX_RETRY_ATTEMPTS = 10
DEFAULT_RETRY_BASE_SECONDS = 60.0
DEFAULT_RETRY_JITTER_PCT = 0.2
MAX_BACKOFF_EXPONENT = 6


@dataclass(slots=True)
class RetryConfig:
    """Configuration options for persistent download retries."""

    max_attempts: int
    base_seconds: float
    jitter_pct: float


def _safe_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _safe_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _load_retry_config() -> RetryConfig:
    """Resolve retry configuration using environment defaults."""

    max_attempts = _safe_int(os.getenv("RETRY_MAX_ATTEMPTS"), DEFAULT_MAX_RETRY_ATTEMPTS)
    base_seconds = _safe_float(os.getenv("RETRY_BASE_SECONDS"), DEFAULT_RETRY_BASE_SECONDS)
    jitter_pct = _safe_float(os.getenv("RETRY_JITTER_PCT"), DEFAULT_RETRY_JITTER_PCT)
    return RetryConfig(max_attempts=max_attempts, base_seconds=base_seconds, jitter_pct=jitter_pct)


def _calculate_backoff_seconds(attempt: int, config: RetryConfig, rng: random.Random) -> float:
    """Return the retry delay for a given attempt applying jitter."""

    bounded_attempt = max(0, min(attempt, MAX_BACKOFF_EXPONENT))
    delay = config.base_seconds * (2**bounded_attempt)
    jitter_pct = max(0.0, config.jitter_pct)
    if jitter_pct:
        jitter_factor = rng.uniform(1 - jitter_pct, 1 + jitter_pct)
    else:
        jitter_factor = 1.0
    return max(0.0, delay * jitter_factor)


def _truncate_error(message: str, limit: int = 512) -> str:
    text = message.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


class DownloadJobError(RuntimeError):
    """Raised when a download job failed but retries have been scheduled."""


class SyncWorker:
    def __init__(
        self,
        soulseek_client: SoulseekClient,
        *,
        base_poll_interval: float = 2.0,
        idle_poll_interval: Optional[float] = None,
        concurrency: Optional[int] = None,
        metadata_worker: MetadataWorker | None = None,
        artwork_worker: ArtworkWorker | None = None,
        lyrics_worker: LyricsWorker | None = None,
        scan_worker: "ScanWorker | None" = None,
    ) -> None:
        self._client = soulseek_client
        self._metadata_worker = metadata_worker
        self._artwork = artwork_worker
        self._lyrics = lyrics_worker
        self._scan_worker = scan_worker
        self._job_store = PersistentJobQueue("sync")
        self._queue: asyncio.PriorityQueue[Tuple[int, int, Optional[QueuedJob]]] = (
            asyncio.PriorityQueue()
        )
        self._enqueue_sequence = 0
        self._manager_task: asyncio.Task | None = None
        self._worker_tasks: List[asyncio.Task] = []
        self._poll_task: asyncio.Task | None = None
        self._running = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._base_poll_interval = base_poll_interval
        self._idle_poll_interval = idle_poll_interval or DEFAULT_IDLE_POLL
        self._current_poll_interval = base_poll_interval
        self._concurrency = max(1, concurrency or self._resolve_concurrency())
        self._cancelled_downloads: Set[int] = set()
        self._cancel_lock = asyncio.Lock()
        self._music_dir = Path(os.getenv("MUSIC_DIR", "./music")).expanduser()
        self._retry_config = _load_retry_config()
        self._retry_rng = random.Random()

    def _resolve_concurrency(self) -> int:
        setting_value = read_setting("sync_worker_concurrency")
        env_value = os.getenv("SYNC_WORKER_CONCURRENCY")
        for value in (setting_value, env_value):
            if not value:
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return DEFAULT_CONCURRENCY

    @staticmethod
    def _coerce_priority(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _extract_file_priority(file_info: Dict[str, Any]) -> int:
        return SyncWorker._coerce_priority(file_info.get("priority"))

    @property
    def queue(self) -> asyncio.PriorityQueue[Tuple[int, int, Optional[QueuedJob]]]:
        return self._queue

    def is_running(self) -> bool:
        return self._running.is_set()

    async def _put_job(self, job: QueuedJob | None) -> None:
        self._enqueue_sequence += 1
        priority = 0 if job is None else max(self._coerce_priority(job.priority), 0)
        await self._queue.put((-priority, self._enqueue_sequence, job))

    async def start(self) -> None:
        if self._manager_task is not None and not self._manager_task.done():
            return
        record_worker_started("sync")
        self._running.set()
        self._stop_event = asyncio.Event()
        self._manager_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._running.is_set():
            return
        self._stop_event.set()
        if self._manager_task is not None:
            try:
                await self._manager_task
            finally:
                self._manager_task = None

    async def enqueue(self, job: Dict[str, Any]) -> None:
        """Submit a download job for processing."""

        record = self._job_store.enqueue(job)
        job_identifier = str(record.id)
        files = job.get("files", [])
        if files:
            now = datetime.utcnow()
            with session_scope() as session:
                for file_info in files:
                    identifier = file_info.get("download_id") or file_info.get("id")
                    try:
                        download_id = int(identifier)
                    except (TypeError, ValueError):
                        continue
                    download = session.get(Download, download_id)
                    if download is None:
                        continue
                    download.job_id = job_identifier
                    download.username = job.get("username") or download.username
                    payload = dict(download.request_payload or {})
                    file_priority = self._extract_file_priority(file_info)
                    if not file_priority:
                        file_priority = self._coerce_priority(job.get("priority"))
                    if not file_priority:
                        file_priority = self._coerce_priority(download.priority)
                    payload["priority"] = file_priority
                    payload["username"] = job.get("username")
                    payload["file"] = dict(file_info)
                    download.request_payload = payload
                    download.state = "queued"
                    download.next_retry_at = None
                    download.updated_at = now
                    session.add(download)

        if self.is_running():
            await self._put_job(record)
            return

        await self._execute_job(record)
        await self.refresh_downloads()

    async def request_cancel(self, download_id: int) -> None:
        """Flag a download for cancellation."""

        async with self._cancel_lock:
            self._cancelled_downloads.add(int(download_id))

    async def _run(self) -> None:
        logger.info("SyncWorker started")
        write_setting("worker.sync.last_start", datetime.utcnow().isoformat())
        record_worker_heartbeat("sync")
        pending = sorted(
            self._job_store.list_pending(),
            key=lambda job: self._coerce_priority(job.priority),
            reverse=True,
        )
        for job in pending:
            await self._put_job(job)

        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(index)) for index in range(self._concurrency)
        ]
        self._poll_task = asyncio.create_task(self._poll_loop())

        try:
            await self._stop_event.wait()
        finally:
            self._running.clear()
            for _ in self._worker_tasks:
                await self._put_job(None)
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            if self._poll_task:
                self._poll_task.cancel()
                try:
                    await self._poll_task
                except asyncio.CancelledError:  # pragma: no cover - lifecycle cleanup
                    pass
            self._job_store.requeue_incomplete()
            write_setting("worker.sync.last_stop", datetime.utcnow().isoformat())
            mark_worker_status("sync", WORKER_STOPPED)
            record_worker_stopped("sync")
            logger.info("SyncWorker stopped")

    async def _worker_loop(self, index: int) -> None:
        logger.debug("SyncWorker task %d started", index)
        while self._running.is_set():
            _, _, job = await self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            try:
                await self._execute_job(job)
                await self.refresh_downloads()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Failed to process sync job %s: %s", job.id, exc)
                record_activity(
                    "download",
                    "sync_job_failed",
                    details={"job_id": job.id, "error": str(exc)},
                )
            finally:
                self._queue.task_done()
        logger.debug("SyncWorker task %d stopped", index)

    async def _poll_loop(self) -> None:
        while self._running.is_set():
            try:
                active_downloads = await self.refresh_downloads()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Download refresh failed: %s", exc)
                active_downloads = False

            interval = (
                self._base_poll_interval
                if active_downloads
                else min(
                    self._idle_poll_interval,
                    max(self._current_poll_interval * 1.5, self._base_poll_interval),
                )
            )
            self._current_poll_interval = interval
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

    async def _execute_job(self, job: QueuedJob) -> None:
        self._job_store.mark_running(job.id)
        try:
            await self._process_job(job.payload)
        except DownloadJobError as exc:
            self._job_store.mark_failed(job.id, str(exc))
            logger.debug("Download job %s marked as failed after scheduling retry", job.id)
            return
        except Exception as exc:
            self._job_store.mark_failed(job.id, str(exc))
            raise
        else:
            self._job_store.mark_completed(job.id)
            increment_counter("metrics.sync.jobs_completed")
            self._record_heartbeat()

    async def _process_job(self, job: Dict[str, Any]) -> None:
        username = job.get("username")
        files = job.get("files", [])
        if not username or not files:
            logger.warning("Invalid download job received: %s", job)
            return

        filtered_files: List[Dict[str, Any]] = []
        async with self._cancel_lock:
            for file_info in files:
                identifier = file_info.get("download_id") or file_info.get("id")
                try:
                    download_id = int(identifier)
                except (TypeError, ValueError):
                    download_id = 0
                if download_id and download_id in self._cancelled_downloads:
                    logger.info("Skipping cancelled download %s in job", download_id)
                    self._cancelled_downloads.discard(download_id)
                    continue
                filtered_files.append(file_info)

        if not filtered_files:
            logger.debug("All downloads in job cancelled before processing")
            return

        now = datetime.utcnow()
        with session_scope() as session:
            for file_info in filtered_files:
                identifier = file_info.get("download_id") or file_info.get("id")
                try:
                    download_id = int(identifier)
                except (TypeError, ValueError):
                    continue
                download = session.get(Download, download_id)
                if download is None or download.state == "dead_letter":
                    continue
                download.state = "downloading"
                download.next_retry_at = None
                download.last_error = None
                download.updated_at = now
                session.add(download)

        try:
            await self._client.download({"username": username, "files": filtered_files})
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to queue Soulseek download: %s", exc)
            await self._handle_download_failure(job, filtered_files, exc)
            raise DownloadJobError(str(exc)) from exc
        else:
            await self._handle_retry_success(filtered_files)

    async def _handle_download_failure(
        self,
        job: Dict[str, Any],
        files: List[Dict[str, Any]],
        error: Exception | str,
    ) -> None:
        if not files:
            return

        scheduled: List[Dict[str, Any]] = []
        dead_letters: List[Dict[str, Any]] = []
        username = job.get("username")
        error_message = _truncate_error(str(error))
        now = datetime.utcnow()

        with session_scope() as session:
            for file_info in files:
                identifier = file_info.get("download_id") or file_info.get("id")
                try:
                    download_id = int(identifier)
                except (TypeError, ValueError):
                    continue

                download = session.get(Download, download_id)
                if download is None:
                    continue

                download.username = username or download.username
                download.retry_count = int(download.retry_count or 0) + 1
                download.last_error = error_message or None
                download.job_id = None
                download.progress = 0.0
                download.updated_at = now

                if download.retry_count > self._retry_config.max_attempts:
                    download.state = "dead_letter"
                    download.next_retry_at = None
                    dead_letters.append(
                        {
                            "download_id": download_id,
                            "retry_count": download.retry_count,
                        }
                    )
                    logger.warning(
                        "event=retry_dead_letter download_id=%s retry_count=%s result=dead_letter",
                        download_id,
                        download.retry_count,
                    )
                else:
                    delay_seconds = _calculate_backoff_seconds(
                        download.retry_count, self._retry_config, self._retry_rng
                    )
                    download.state = "failed"
                    download.next_retry_at = now + timedelta(seconds=delay_seconds)
                    scheduled.append(
                        {
                            "download_id": download_id,
                            "retry_count": download.retry_count,
                            "delay_seconds": delay_seconds,
                            "next_retry_at": download.next_retry_at.isoformat(),
                        }
                    )
                    logger.info(
                        "event=retry_schedule download_id=%s retry_count=%s next_retry_at=%s result=scheduled",
                        download_id,
                        download.retry_count,
                        download.next_retry_at.isoformat(),
                    )

                session.add(download)

        if scheduled:
            record_activity(
                "download",
                DOWNLOAD_RETRY_SCHEDULED,
                details={
                    "downloads": scheduled,
                    "username": username,
                },
            )
        if dead_letters:
            record_activity(
                "download",
                DOWNLOAD_RETRY_FAILED,
                details={
                    "downloads": dead_letters,
                    "username": username,
                    "error": error_message,
                },
            )

    async def _handle_retry_success(self, files: Iterable[Dict[str, Any]]) -> None:
        completed: List[Dict[str, Any]] = []
        now = datetime.utcnow()
        with session_scope() as session:
            for file_info in files:
                identifier = file_info.get("download_id") or file_info.get("id")
                try:
                    download_id = int(identifier)
                except (TypeError, ValueError):
                    continue

                download = session.get(Download, download_id)
                if download is None:
                    continue

                attempts = int(download.retry_count or 0)
                download.next_retry_at = None
                download.last_error = None
                download.state = "downloading"
                download.updated_at = now
                session.add(download)

                if attempts > 0:
                    completed.append({"download_id": download_id, "retry_count": attempts})
                    logger.info(
                        "event=retry_enqueue download_id=%s retry_count=%s result=enqueued",
                        download_id,
                        attempts,
                    )

        if completed:
            record_activity(
                "download",
                DOWNLOAD_RETRY_COMPLETED,
                details={"downloads": completed},
            )

    async def refresh_downloads(self) -> bool:
        """Poll Soulseek for download progress and persist it."""

        try:
            response = await self._client.get_download_status()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Unable to obtain Soulseek download status: %s", exc)
            return False

        downloads: Iterable[Dict[str, Any]]
        if isinstance(response, dict):
            downloads = response.get("downloads", []) or []
        elif isinstance(response, list):
            downloads = response
        else:  # pragma: no cover - defensive
            downloads = []

        active = False
        async with self._cancel_lock:
            pending_cancels = set(self._cancelled_downloads)

        to_cancel: List[int] = []
        completed_downloads: List[Tuple[int, Dict[str, Any]]] = []
        with session_scope() as session:
            for payload in downloads:
                download_id = payload.get("download_id") or payload.get("id")
                if download_id is None:
                    continue

                download = session.get(Download, int(download_id))
                if download is None:
                    continue
                if download.state == "dead_letter":
                    continue

                previous_state = download.state
                state = str(payload.get("state", previous_state))
                if state not in ALLOWED_STATES:
                    state = previous_state

                progress_value = payload.get("progress", download.progress)
                try:
                    progress = float(progress_value)
                except (TypeError, ValueError):
                    progress = download.progress

                if progress < 0:
                    progress = 0.0
                elif progress > 100:
                    progress = 100.0

                if state == "queued" and 0 < progress < 100:
                    state = "downloading"
                elif state == "completed":
                    progress = 100.0
                elif state in {"queued", "downloading"}:
                    active = True

                if int(download_id) in pending_cancels:
                    if state in {"queued", "downloading"}:
                        to_cancel.append(int(download_id))
                    state = "cancelled"
                    pending_cancels.discard(int(download_id))
                    active = False

                download.state = state
                download.progress = progress
                download.updated_at = datetime.utcnow()
                if state == "completed" and previous_state != "completed":
                    completed_downloads.append((int(download_id), dict(payload)))

        if active:
            write_setting("metrics.sync.active_downloads", "1")
        else:
            write_setting("metrics.sync.active_downloads", "0")
        self._record_heartbeat()

        if to_cancel:
            for identifier in to_cancel:
                try:
                    await self._client.cancel_download(str(identifier))
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Failed to cancel download %s via client: %s", identifier, exc)
            async with self._cancel_lock:
                for identifier in to_cancel:
                    self._cancelled_downloads.discard(identifier)

        for identifier, payload in completed_downloads:
            try:
                await self._handle_download_completion(identifier, payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to enrich metadata for download %s: %s", identifier, exc)

        return active

    def _record_heartbeat(self) -> None:
        record_worker_heartbeat("sync")

    async def _handle_download_completion(self, download_id: int, payload: Dict[str, Any]) -> None:
        with session_scope() as session:
            download = session.get(Download, download_id)
            if download is None:
                return
            request_payload = dict(download.request_payload or {})
            filename = download.filename

        file_path = self._resolve_download_path(payload, request_payload) or filename
        metadata: Dict[str, Any] = {}
        artwork_url: Optional[str] = None
        if file_path and self._metadata_worker is not None:
            try:
                metadata = await self._metadata_worker.enqueue(
                    download_id,
                    Path(file_path),
                    payload=payload,
                    request_payload=request_payload,
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug("Metadata worker failed for download %s: %s", download_id, exc)
            else:
                artwork_url = metadata.get("artwork_url")

        metadata = dict(metadata or {})
        for source in (request_payload, payload):
            for key, value in self._extract_basic_metadata(source).items():
                metadata.setdefault(key, value)

        if not artwork_url:
            fallback_artwork = self._resolve_text(
                ("artwork_url", "cover_url", "image_url", "thumbnail", "thumb"),
                metadata,
                payload,
                request_payload,
            )
            if fallback_artwork:
                artwork_url = fallback_artwork
                metadata.setdefault("artwork_url", artwork_url)

        spotify_track_id = self._extract_spotify_id(request_payload)
        if not spotify_track_id:
            spotify_track_id = self._extract_spotify_id(payload)

        spotify_album_id = self._extract_spotify_album_id(
            metadata,
            payload,
            request_payload,
        )

        if download_id is not None:
            with session_scope() as session:
                record = session.get(Download, download_id)
                if record is not None:
                    record.state = "completed"
                    record.retry_count = 0
                    record.next_retry_at = None
                    record.last_error = None
                    record.job_id = None
                    organized_path: Path | None = None
                    if file_path:
                        record.filename = str(file_path)
                        existing_path = (
                            Path(record.organized_path)
                            if isinstance(record.organized_path, str)
                            else None
                        )
                        if existing_path is not None and existing_path.exists():
                            file_path = str(existing_path)
                            record.filename = file_path
                        else:
                            payload_copy: Dict[str, Any] = dict(record.request_payload or {})
                            nested_metadata: Dict[str, Any] = dict(
                                payload_copy.get("metadata") or {}
                            )
                            for key, value in metadata.items():
                                if isinstance(value, (str, int, float)):
                                    text = str(value).strip()
                                    if text and key not in nested_metadata:
                                        nested_metadata[key] = text
                            if nested_metadata:
                                payload_copy["metadata"] = nested_metadata
                                record.request_payload = payload_copy
                            try:
                                organized_path = organize_file(record, self._music_dir)
                            except FileNotFoundError:
                                logger.debug(
                                    "Download file missing for organization: %s",
                                    file_path,
                                )
                            except Exception as exc:  # pragma: no cover - defensive
                                logger.warning(
                                    "Failed to organise download %s: %s",
                                    download_id,
                                    exc,
                                )
                            else:
                                file_path = str(organized_path)

                    if spotify_track_id:
                        record.spotify_track_id = spotify_track_id
                    if spotify_album_id:
                        record.spotify_album_id = spotify_album_id
                    if artwork_url:
                        record.artwork_url = artwork_url
                    if organized_path is not None:
                        record.organized_path = str(organized_path)
                        record.filename = str(organized_path)
                    record.updated_at = datetime.utcnow()
                    session.add(record)

        if self._artwork is not None and file_path:
            try:
                await self._artwork.enqueue(
                    download_id,
                    str(file_path),
                    metadata=dict(metadata),
                    spotify_track_id=spotify_track_id,
                    spotify_album_id=spotify_album_id,
                    artwork_url=artwork_url,
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug(
                    "Failed to schedule artwork embedding for download %s: %s",
                    download_id,
                    exc,
                )

        if self._lyrics is not None and file_path:
            track_info: Dict[str, Any] = dict(metadata)
            track_info.setdefault("filename", filename)
            track_info.setdefault("download_id", download_id)
            if spotify_track_id:
                track_info.setdefault("spotify_track_id", spotify_track_id)

            title = track_info.get("title") or self._resolve_text(
                ("title", "track", "name", "filename"),
                metadata,
                payload,
                request_payload,
            )
            track_info["title"] = title or filename

            artist = track_info.get("artist") or self._resolve_text(
                ("artist", "artist_name", "artists"),
                metadata,
                payload,
                request_payload,
            )
            if artist:
                track_info["artist"] = artist

            album = track_info.get("album") or self._resolve_text(
                ("album", "album_name", "release"),
                metadata,
                payload,
                request_payload,
            )
            if album:
                track_info["album"] = album

            duration = track_info.get("duration") or self._resolve_text(
                ("duration", "duration_ms", "durationMs", "length"),
                metadata,
                payload,
                request_payload,
            )
            if duration:
                track_info["duration"] = duration

            try:
                await self._lyrics.enqueue(download_id, file_path, track_info)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug(
                    "Failed to schedule lyrics generation for download %s: %s",
                    download_id,
                    exc,
                )

        if self._scan_worker is not None:
            try:
                await self._scan_worker.request_scan()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug(
                    "Unable to enqueue Plex scan after download %s: %s",
                    download_id,
                    exc,
                )

    @staticmethod
    def _extract_spotify_id(payload: Mapping[str, Any] | None) -> Optional[str]:
        if not isinstance(payload, Mapping):
            return None
        keys = (
            "spotify_id",
            "spotifyId",
            "spotify_track_id",
            "spotifyTrackId",
            "spotify_track",
        )
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, Mapping):
                nested = value.get("id")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
        nested = payload.get("track")
        if isinstance(nested, Mapping):
            candidate = nested.get("spotify_id") or nested.get("id")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None

    @staticmethod
    def _extract_spotify_album_id(
        *payloads: Mapping[str, Any] | None,
    ) -> Optional[str]:
        for payload in payloads:
            if not isinstance(payload, Mapping):
                continue
            direct = payload.get("spotify_album_id") or payload.get("album_id")
            if isinstance(direct, str) and direct.strip():
                return direct.strip()
            album_payload = payload.get("album")
            if isinstance(album_payload, Mapping):
                for key in ("spotify_id", "spotifyId", "id"):
                    value = album_payload.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            track_payload = payload.get("track")
            if isinstance(track_payload, Mapping):
                album_info = track_payload.get("album")
                if isinstance(album_info, Mapping):
                    for key in ("spotify_id", "spotifyId", "id"):
                        value = album_info.get(key)
                        if isinstance(value, str) and value.strip():
                            return value.strip()
        return None

    @staticmethod
    def _resolve_download_path(
        *payloads: Mapping[str, Any] | None,
    ) -> Optional[str]:
        for payload in payloads:
            if not isinstance(payload, Mapping):
                continue
            for key in (
                "local_path",
                "localPath",
                "path",
                "file_path",
                "filePath",
                "filename",
            ):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    @staticmethod
    def _normalise_metadata_value(value: Any) -> Optional[str]:
        if isinstance(value, str):
            text = value.strip()
            return text or None
        if isinstance(value, (int, float)):
            text = str(value).strip()
            return text or None
        if isinstance(value, Mapping):
            for key in ("name", "title", "value"):
                nested = SyncWorker._normalise_metadata_value(value.get(key))
                if nested:
                    return nested
        if isinstance(value, list) and value:
            return SyncWorker._normalise_metadata_value(value[0])
        return None

    @staticmethod
    def _resolve_text(
        keys: Iterable[str],
        *payloads: Mapping[str, Any] | None,
    ) -> Optional[str]:
        for payload in payloads:
            if not isinstance(payload, Mapping):
                continue
            for key in keys:
                if key not in payload:
                    continue
                candidate = SyncWorker._normalise_metadata_value(payload.get(key))
                if candidate:
                    return candidate
                nested = payload.get("metadata")
                if isinstance(nested, Mapping):
                    nested_value = SyncWorker._resolve_text(keys, nested)
                    if nested_value:
                        return nested_value
        return None

    @staticmethod
    def _extract_basic_metadata(payload: Mapping[str, Any] | None) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        if not isinstance(payload, Mapping):
            return metadata
        keys = ("genre", "composer", "producer", "isrc", "copyright", "artwork_url")
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (str, int, float)):
                text = str(value).strip()
                if text:
                    metadata[key] = text
        nested = payload.get("metadata")
        if isinstance(nested, Mapping):
            for key, value in SyncWorker._extract_basic_metadata(nested).items():
                metadata.setdefault(key, value)
        return metadata
