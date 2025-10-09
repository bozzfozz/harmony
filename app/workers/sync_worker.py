"""Background worker for processing Soulseek download jobs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import random
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.config import get_env
from app.core.soulseek_client import SoulseekClient
from app.db import run_session
from app.logging import get_logger
from app.models import Download, IngestItemState
from app.orchestrator.handlers import (
    SyncHandlerDeps,
    calculate_retry_backoff_seconds as orchestrator_calculate_backoff_seconds,
    extract_basic_metadata,
    extract_ingest_item_id,
    extract_spotify_album_id,
    extract_spotify_id,
    fanout_download_completion,
    handle_sync_download_failure,
    handle_sync_retry_success,
    process_sync_payload,
    resolve_download_path,
    resolve_text,
    truncate_error,
    update_ingest_item_state,
)
from app.services.retry_policy_provider import RetryPolicy, get_retry_policy_provider
from app.utils.activity import record_activity, record_worker_started, record_worker_stopped
from app.utils.events import WORKER_STOPPED
from app.utils.settings_store import increment_counter, read_setting, write_setting
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat
from app.workers.artwork_worker import ArtworkWorker
from app.workers.lyrics_worker import LyricsWorker
from app.workers.metadata_worker import MetadataWorker
from app.workers.persistence import (
    QueueJobDTO,
    complete_async,
    enqueue_async,
    fail_async,
    fetch_ready_async,
    lease_async,
    release_active_leases_async,
)

# Backwards compatible alias used by existing tests and callers relying on the
# original synchronous API facade.
enqueue = enqueue_async

AsyncEnqueue = Callable[[str, Mapping[str, Any]], Awaitable[QueueJobDTO]]
AsyncFetchReady = Callable[[str], Awaitable[List[QueueJobDTO]]]
AsyncLease = Callable[[int, str, Optional[int]], Awaitable[QueueJobDTO | None]]
AsyncComplete = Callable[[int, str, Optional[Mapping[str, Any]]], Awaitable[bool]]
AsyncFail = Callable[
    [int, str, Optional[str], Optional[int], Optional[datetime], Optional[str]],
    Awaitable[bool],
]
AsyncRelease = Callable[[str], Awaitable[None]]


@dataclass(slots=True)
class _PriorityQueueEntry:
    """Internal representation of a queued job with its priority metadata."""

    queue_priority: int
    sequence: int
    job: QueueJobDTO

    @property
    def effective_priority(self) -> int:
        """Return the original (non-negated) priority value."""

        return -self.queue_priority


async def _default_lease_job(
    job_id: int, job_type: str, lease_seconds: int | None = None
) -> QueueJobDTO | None:
    return await lease_async(job_id, job_type=job_type, lease_seconds=lease_seconds)


async def _default_complete_job(
    job_id: int, job_type: str, result_payload: Mapping[str, Any] | None = None
) -> bool:
    return await complete_async(job_id, job_type=job_type, result_payload=result_payload)


async def _default_fail_job(
    job_id: int,
    job_type: str,
    error: str | None = None,
    retry_in: int | None = None,
    available_at: datetime | None = None,
    stop_reason: str | None = None,
) -> bool:
    return await fail_async(
        job_id,
        job_type=job_type,
        error=error,
        retry_in=retry_in,
        available_at=available_at,
        stop_reason=stop_reason,
    )


async def _default_release_active_leases(job_type: str) -> None:
    await release_active_leases_async(job_type)


logger = get_logger(__name__)

ALLOWED_STATES = {"queued", "downloading", "completed", "failed", "cancelled", "dead_letter"}

DEFAULT_CONCURRENCY = 2
DEFAULT_IDLE_POLL = 15.0

RetryConfig = RetryPolicy


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


def _calculate_backoff_seconds(attempt: int, config: RetryConfig, rng: random.Random) -> float:
    return orchestrator_calculate_backoff_seconds(attempt, config, rng)


def _truncate_error(message: str, limit: int = 512) -> str:
    return truncate_error(message, limit)


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
        enqueue_fn: AsyncEnqueue | None = None,
        fetch_ready_fn: AsyncFetchReady | None = None,
        lease_fn: AsyncLease | None = None,
        complete_fn: AsyncComplete | None = None,
        fail_fn: AsyncFail | None = None,
        release_active_leases_fn: AsyncRelease | None = None,
    ) -> None:
        self._client = soulseek_client
        self._metadata_worker = metadata_worker
        self._artwork = artwork_worker
        self._lyrics = lyrics_worker
        self._job_type = "sync"
        self._queue: asyncio.PriorityQueue[Tuple[int, int, Optional[QueueJobDTO]]] = (
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
        self._music_dir = Path(get_env("MUSIC_DIR") or "./music").expanduser()
        self._retry_provider = get_retry_policy_provider()
        self._retry_config = self._retry_provider.get_retry_policy("sync")
        self._retry_rng = random.Random()
        self._enqueue_job = enqueue_fn or enqueue_async
        self._fetch_ready_jobs = fetch_ready_fn or fetch_ready_async
        self._lease_job = lease_fn or _default_lease_job
        self._complete_job = complete_fn or _default_complete_job
        self._fail_job = fail_fn or _default_fail_job
        self._release_active_leases = release_active_leases_fn or _default_release_active_leases
        self._priority_event = asyncio.Event()
        self._priority_reorder_window = 0.02

    def _resolve_concurrency(self) -> int:
        setting_value = read_setting("sync_worker_concurrency")
        env_value = get_env("SYNC_WORKER_CONCURRENCY")
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

    @property
    def retry_policy(self) -> RetryConfig:
        return self._retry_config

    def refresh_retry_policy(self) -> None:
        """Reload the retry policy from the latest runtime configuration."""

        self._retry_provider.invalidate("sync")
        self._retry_config = self._retry_provider.get_retry_policy("sync")

    @staticmethod
    def _extract_file_priority(file_info: Dict[str, Any]) -> int:
        return SyncWorker._coerce_priority(file_info.get("priority"))

    @property
    def queue(self) -> asyncio.PriorityQueue[Tuple[int, int, Optional[QueueJobDTO]]]:
        return self._queue

    def is_running(self) -> bool:
        return self._running.is_set()

    def _build_handler_deps(self) -> SyncHandlerDeps:
        return SyncHandlerDeps(
            soulseek_client=self._client,
            metadata_service=self._metadata_worker,
            artwork_service=self._artwork,
            lyrics_service=self._lyrics,
            music_dir=self._music_dir,
            retry_policy_provider=self._retry_provider,
            rng=self._retry_rng,
        )

    async def _put_job(self, job: QueueJobDTO | None) -> None:
        self._enqueue_sequence += 1
        priority = 0 if job is None else max(self._coerce_priority(job.priority), 0)
        await self._queue.put((-priority, self._enqueue_sequence, job))
        self._priority_event.set()

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

        record = await self._enqueue_job(self._job_type, job)
        job_identifier = str(record.id)
        files = job.get("files", [])
        if files:
            now = datetime.utcnow()

            def _update_downloads(session: Session) -> None:
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

            await run_session(_update_downloads)

        if self.is_running():
            await self._put_job(record)
            return

        priority_value = -max(self._coerce_priority(record.priority), 0)
        processed = await self._execute_job(record, priority_value)
        if processed:
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
            await self._fetch_ready_jobs(self._job_type),
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
            try:
                for _ in self._worker_tasks:
                    await self._put_job(None)
                await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            finally:
                self._worker_tasks = []
                self._running.clear()
            if self._poll_task:
                self._poll_task.cancel()
                try:
                    await self._poll_task
                except asyncio.CancelledError:  # pragma: no cover - lifecycle cleanup
                    pass
                self._poll_task = None
            await self._release_active_leases(self._job_type)
            write_setting("worker.sync.last_stop", datetime.utcnow().isoformat())
            mark_worker_status("sync", WORKER_STOPPED)
            record_worker_stopped("sync")
            logger.info("SyncWorker stopped")

    async def _worker_loop(self, index: int) -> None:
        logger.debug("SyncWorker task %d started", index)
        while self._running.is_set():
            priority, sequence, job = await self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            try:
                await self._process_job_with_priority(priority, sequence, job)
            finally:
                self._queue.task_done()
        logger.debug("SyncWorker task %d stopped", index)

    async def _process_job_with_priority(
        self, priority: int, sequence: int, job: QueueJobDTO
    ) -> None:
        await self._drain_higher_priority_jobs(priority)
        await self._handle_queue_job(priority, job)

    async def _drain_higher_priority_jobs(self, current_priority: int) -> None:
        while True:
            candidate = await self._maybe_take_preempting_job(current_priority)
            if candidate is None:
                return
            try:
                await self._process_job_with_priority(
                    candidate.queue_priority, candidate.sequence, candidate.job
                )
            finally:
                self._queue.task_done()

    async def _maybe_take_preempting_job(
        self, current_priority: int
    ) -> Optional[_PriorityQueueEntry]:
        await asyncio.sleep(0)
        candidate = self._peek_higher_priority_entry(current_priority)
        if candidate is None:
            return None
        try:
            priority, sequence, job = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None
        if job is None:
            self._queue.task_done()
            await self._queue.put((priority, sequence, job))
            return None
        if priority >= current_priority:
            self._queue.task_done()
            await self._queue.put((priority, sequence, job))
            return None
        return _PriorityQueueEntry(priority, sequence, job)

    async def _handle_queue_job(self, priority: int, job: QueueJobDTO) -> None:
        try:
            processed = await self._execute_job(job, priority)
            if processed:
                await self.refresh_downloads()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to process sync job %s: %s", job.id, exc)
            record_activity(
                "download",
                "sync_job_failed",
                details={"job_id": job.id, "error": str(exc)},
            )

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

    async def _execute_job(self, job: QueueJobDTO, priority: int) -> bool:
        if await self._maybe_defer_before_lease(priority, job):
            return False

        leased = await self._lease_job(
            job.id,
            self._job_type,
            job.lease_timeout_seconds,
        )
        if leased is None:
            logger.debug("Sync job %s skipped because it could not be leased", job.id)
            return False

        if await self._maybe_preempt_after_lease(priority, leased):
            return False

        if await self._maybe_preempt_before_execution(priority, leased):
            return False
        try:
            await self._process_job(leased.payload)
        except DownloadJobError as exc:
            await self._fail_job(
                job.id,
                self._job_type,
                str(exc),
                retry_in=None,
                available_at=None,
                stop_reason=None,
            )
            logger.debug("Download job %s marked as failed after scheduling retry", job.id)
            return True
        except Exception as exc:
            await self._fail_job(
                job.id,
                self._job_type,
                str(exc),
                retry_in=None,
                available_at=None,
                stop_reason=None,
            )
            raise
        else:
            await self._complete_job(
                job.id,
                self._job_type,
                result_payload=None,
            )
            increment_counter("metrics.sync.jobs_completed")
            self._record_heartbeat()
            return True

    async def _maybe_defer_before_lease(self, current_priority: int, job: QueueJobDTO) -> bool:
        candidate = await self._wait_for_higher_priority(current_priority)
        if candidate is None:
            return False

        await self._put_job(job)
        self._record_priority_reorder(
            stage="before_lease",
            preempted_job=job,
            preempted_priority=-current_priority,
            next_job=candidate.job,
            next_priority=candidate.effective_priority,
        )
        return True

    async def _maybe_preempt_after_lease(self, current_priority: int, leased: QueueJobDTO) -> bool:
        candidate = await self._wait_for_higher_priority(current_priority)
        if candidate is None:
            return False

        return await self._preempt_leased_job(
            stage="after_lease",
            current_priority=current_priority,
            preempted=leased,
            candidate=candidate,
        )

    async def _maybe_preempt_before_execution(
        self, current_priority: int, leased: QueueJobDTO
    ) -> bool:
        candidate = await self._wait_for_higher_priority(current_priority)
        if candidate is None:
            return False

        return await self._preempt_leased_job(
            stage="before_execute",
            current_priority=current_priority,
            preempted=leased,
            candidate=candidate,
        )

    async def _preempt_leased_job(
        self,
        *,
        stage: str,
        current_priority: int,
        preempted: QueueJobDTO,
        candidate: _PriorityQueueEntry,
    ) -> bool:
        rescheduled = await self._fail_job(
            preempted.id,
            self._job_type,
            error=None,
            retry_in=0,
            available_at=None,
            stop_reason=None,
        )
        if not rescheduled:
            logger.warning(
                "Failed to reschedule sync job %s for higher priority job %s during %s",
                preempted.id,
                candidate.job.id,
                stage,
            )
            return False

        await self._put_job(preempted)
        self._record_priority_reorder(
            stage=stage,
            preempted_job=preempted,
            preempted_priority=-current_priority,
            next_job=candidate.job,
            next_priority=candidate.effective_priority,
        )
        return True

    async def _wait_for_higher_priority(
        self, current_priority: int
    ) -> Optional[_PriorityQueueEntry]:
        candidate = self._peek_higher_priority_entry(current_priority)
        if candidate is not None:
            return candidate

        self._priority_event.clear()
        candidate = self._peek_higher_priority_entry(current_priority)
        if candidate is not None:
            return candidate

        try:
            await asyncio.wait_for(
                self._priority_event.wait(), timeout=self._priority_reorder_window
            )
        except asyncio.TimeoutError:
            return self._peek_higher_priority_entry(current_priority)

        return self._peek_higher_priority_entry(current_priority)

    def _peek_queue_entry(self) -> Optional[_PriorityQueueEntry]:
        if self._queue.empty():
            return None
        try:
            queue_priority, sequence, job = self._queue._queue[0]
        except IndexError:  # pragma: no cover - defensive
            return None
        if job is None:
            return None
        return _PriorityQueueEntry(queue_priority, sequence, job)

    def _peek_higher_priority_entry(self, current_priority: int) -> Optional[_PriorityQueueEntry]:
        candidate = self._peek_queue_entry()
        if candidate is None:
            return None
        if candidate.queue_priority >= current_priority:
            return None
        return candidate

    def _record_priority_reorder(
        self,
        *,
        stage: str,
        preempted_job: QueueJobDTO,
        preempted_priority: int,
        next_job: QueueJobDTO,
        next_priority: int,
    ) -> None:
        increment_counter("metrics.sync.jobs_preempted")
        increment_counter(f"metrics.sync.jobs_preempted.{stage}")
        record_activity(
            "download",
            "sync_job_preempted",
            details={
                "preempted_job_id": preempted_job.id,
                "preempted_priority": preempted_priority,
                "next_job_id": next_job.id,
                "next_job_priority": next_priority,
                "stage": stage,
            },
        )
        logger.info(
            "Priority reorder (%s): defer job %s (priority=%d) for job %s (priority=%d)",
            stage,
            preempted_job.id,
            preempted_priority,
            next_job.id,
            next_priority,
        )

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

        payload = dict(job)
        payload["files"] = filtered_files
        deps = self._build_handler_deps()

        try:
            await process_sync_payload(payload, deps)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to queue Soulseek download: %s", exc)
            raise DownloadJobError(str(exc)) from exc

    async def _handle_download_failure(
        self,
        job: Dict[str, Any],
        files: List[Dict[str, Any]],
        error: Exception | str,
    ) -> None:
        deps = self._build_handler_deps()
        await handle_sync_download_failure(job, files, deps, error)

    async def _handle_retry_success(self, files: Iterable[Dict[str, Any]]) -> None:
        deps = self._build_handler_deps()
        await handle_sync_retry_success(files, deps)

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

        def _update_progress(
            session: Session,
        ) -> tuple[bool, List[int], List[Tuple[int, Dict[str, Any]]]]:
            active_flag = False
            to_cancel_local: List[int] = []
            completed_local: List[Tuple[int, Dict[str, Any]]] = []

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
                    active_flag = True

                if int(download_id) in pending_cancels:
                    if state in {"queued", "downloading"}:
                        to_cancel_local.append(int(download_id))
                    state = "cancelled"
                    pending_cancels.discard(int(download_id))
                    active_flag = False

                download.state = state
                download.progress = progress
                download.updated_at = datetime.utcnow()
                if state == "completed" and previous_state != "completed":
                    completed_local.append((int(download_id), dict(payload)))

            return active_flag, to_cancel_local, completed_local

        active, to_cancel, completed_downloads = await run_session(_update_progress)

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
        deps = self._build_handler_deps()
        await fanout_download_completion(download_id, payload, deps)

    @staticmethod
    def _extract_ingest_item_id(*payloads: Mapping[str, Any] | None) -> Optional[int]:
        return extract_ingest_item_id(*payloads)

    @staticmethod
    def _update_ingest_item_state(
        item_id: int,
        state: IngestItemState | str,
        *,
        error: Optional[str],
    ) -> None:
        update_ingest_item_state(item_id, state, error=error)

    @staticmethod
    def _extract_spotify_id(payload: Mapping[str, Any] | None) -> Optional[str]:
        return extract_spotify_id(payload)

    @staticmethod
    def _extract_spotify_album_id(
        *payloads: Mapping[str, Any] | None,
    ) -> Optional[str]:
        return extract_spotify_album_id(*payloads)

    @staticmethod
    def _resolve_download_path(
        *payloads: Mapping[str, Any] | None,
    ) -> Optional[str]:
        return resolve_download_path(*payloads)

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
        return resolve_text(keys, *payloads)

    @staticmethod
    def _extract_basic_metadata(payload: Mapping[str, Any] | None) -> Dict[str, str]:
        return extract_basic_metadata(payload)
