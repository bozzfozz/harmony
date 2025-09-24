"""Background worker for processing Soulseek download jobs."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set

from app.core.soulseek_client import SoulseekClient
from app.db import session_scope
from app.logging import get_logger
from app.models import Download
from app.utils.activity import record_activity
from app.utils.settings_store import increment_counter, read_setting, write_setting
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat
from app.workers.persistence import PersistentJobQueue, QueuedJob

logger = get_logger(__name__)

ALLOWED_STATES = {"queued", "downloading", "completed", "failed", "cancelled"}

DEFAULT_CONCURRENCY = 2
DEFAULT_IDLE_POLL = 15.0


class SyncWorker:
    def __init__(
        self,
        soulseek_client: SoulseekClient,
        *,
        base_poll_interval: float = 2.0,
        idle_poll_interval: Optional[float] = None,
        concurrency: Optional[int] = None,
    ) -> None:
        self._client = soulseek_client
        self._job_store = PersistentJobQueue("sync")
        self._queue: asyncio.Queue[QueuedJob | None] = asyncio.Queue()
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

    @property
    def queue(self) -> asyncio.Queue[QueuedJob | None]:
        return self._queue

    def is_running(self) -> bool:
        return self._running.is_set()

    async def start(self) -> None:
        if self._manager_task is not None and not self._manager_task.done():
            return
        self._running.set()
        self._stop_event = asyncio.Event()
        self._manager_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._running.is_set():
            return
        self._stop_event.set()
        if self._manager_task is not None:
            await self._manager_task

    async def enqueue(self, job: Dict[str, Any]) -> None:
        """Submit a download job for processing."""

        record = self._job_store.enqueue(job)
        if self.is_running():
            await self._queue.put(record)
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
        pending = self._job_store.list_pending()
        for job in pending:
            await self._queue.put(job)

        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(index))
            for index in range(self._concurrency)
        ]
        self._poll_task = asyncio.create_task(self._poll_loop())

        try:
            await self._stop_event.wait()
        finally:
            for _ in self._worker_tasks:
                await self._queue.put(None)
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            if self._poll_task:
                self._poll_task.cancel()
                try:
                    await self._poll_task
                except asyncio.CancelledError:  # pragma: no cover - lifecycle cleanup
                    pass
            self._job_store.requeue_incomplete()
            write_setting("worker.sync.last_stop", datetime.utcnow().isoformat())
            self._running.clear()
            mark_worker_status("sync", "stopped")
            logger.info("SyncWorker stopped")

    async def _worker_loop(self, index: int) -> None:
        logger.debug("SyncWorker task %d started", index)
        while self._running.is_set():
            job = await self._queue.get()
            if job is None:
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
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Download refresh failed: %s", exc)
                active_downloads = False

            interval = self._base_poll_interval if active_downloads else min(
                self._idle_poll_interval, max(self._current_poll_interval * 1.5, self._base_poll_interval)
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

        try:
            await self._client.download({"username": username, "files": filtered_files})
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to queue Soulseek download: %s", exc)
            self._mark_failed(filtered_files)
            raise

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
        with session_scope() as session:
            for payload in downloads:
                download_id = payload.get("download_id") or payload.get("id")
                if download_id is None:
                    continue

                download = session.get(Download, int(download_id))
                if download is None:
                    continue

                state = str(payload.get("state", download.state))
                if state not in ALLOWED_STATES:
                    state = download.state

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

        return active

    def _mark_failed(self, files: Iterable[Dict[str, Any]]) -> None:
        download_ids = []
        for file_info in files:
            identifier = file_info.get("download_id") or file_info.get("id")
            if identifier is not None:
                download_ids.append(int(identifier))

        if not download_ids:
            return

        with session_scope() as session:
            for download_id in download_ids:
                download = session.get(Download, download_id)
                if download is None:
                    continue
                download.state = "failed"
                download.updated_at = datetime.utcnow()

    def _record_heartbeat(self) -> None:
        record_worker_heartbeat("sync")
