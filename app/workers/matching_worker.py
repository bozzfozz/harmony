"""Background worker handling deferred matching operations."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List

from app.config import get_env
from app.core.matching_engine import MusicMatchingEngine
from app.db import session_scope
from app.logging import get_logger
from app.orchestrator.handlers import (
    MatchingHandlerDeps,
    MatchingJobError,
    handle_matching,
)
from app.utils.activity import (
    record_activity,
    record_worker_started,
    record_worker_stopped,
)
from app.utils.events import WORKER_STOPPED
from app.utils.settings_store import read_setting, write_setting
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat
from app.workers.persistence import (
    QueueJobDTO,
    complete,
    enqueue,
    fail,
    fetch_ready,
    lease,
    release_active_leases,
    to_dlq,
)

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 5
DEFAULT_THRESHOLD = 0.65


class MatchingWorker:
    def __init__(
        self,
        engine: MusicMatchingEngine,
        *,
        batch_size: int | None = None,
        confidence_threshold: float | None = None,
        batch_wait_seconds: float = 0.1,
    ) -> None:
        self._engine = engine
        self._job_type = "matching"
        self._queue: asyncio.Queue[QueueJobDTO | None] = asyncio.Queue()
        self._manager_task: asyncio.Task | None = None
        self._worker_task: asyncio.Task | None = None
        self._running = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._batch_wait = batch_wait_seconds
        self._batch_size = max(1, batch_size or self._resolve_batch_size())
        resolved_threshold: float | None = None
        if confidence_threshold is not None and 0 < confidence_threshold <= 1:
            resolved_threshold = confidence_threshold
        if resolved_threshold is None:
            resolved_threshold = self._resolve_threshold()
        self._handler_deps = MatchingHandlerDeps(
            engine=self._engine,
            session_factory=session_scope,
            confidence_threshold=resolved_threshold,
        )

    def _resolve_batch_size(self) -> int:
        setting_value = read_setting("matching_worker_batch_size")
        env_value = get_env("MATCHING_WORKER_BATCH_SIZE")
        for value in (setting_value, env_value):
            if not value:
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return DEFAULT_BATCH_SIZE

    def _resolve_threshold(self) -> float:
        setting_value = read_setting("matching_confidence_threshold")
        env_value = get_env("MATCHING_CONFIDENCE_THRESHOLD")
        for value in (setting_value, env_value):
            if not value:
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if 0 < parsed <= 1:
                return parsed
        return DEFAULT_THRESHOLD

    async def start(self) -> None:
        if self._manager_task is not None and not self._manager_task.done():
            return
        record_worker_started("matching")
        self._running.set()
        self._stop_event = asyncio.Event()
        self._manager_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._running.is_set():
            return
        self._stop_event.set()
        if self._manager_task is not None:
            await self._manager_task

    @property
    def queue(self) -> asyncio.Queue[QueueJobDTO | None]:
        return self._queue

    async def enqueue(self, payload: Dict[str, Any]) -> None:
        job = enqueue(self._job_type, payload)
        if self._running.is_set():
            await self._queue.put(job)
        else:
            await self._process_batch([job])

    async def _run(self) -> None:
        logger.info("MatchingWorker started")
        write_setting("worker.matching.last_start", datetime.utcnow().isoformat())
        record_worker_heartbeat("matching")
        pending = fetch_ready(self._job_type)
        for job in pending:
            await self._queue.put(job)

        self._worker_task = asyncio.create_task(self._worker_loop())

        try:
            await self._stop_event.wait()
        finally:
            await self._queue.put(None)
            if self._worker_task:
                await self._worker_task
            release_active_leases(self._job_type)
            self._running.clear()
            write_setting("worker.matching.last_stop", datetime.utcnow().isoformat())
            mark_worker_status("matching", WORKER_STOPPED)
            record_worker_stopped("matching")
            logger.info("MatchingWorker stopped")

    async def _worker_loop(self) -> None:
        while self._running.is_set():
            first_job = await self._queue.get()
            if first_job is None:
                self._queue.task_done()
                break
            batch = [first_job]
            while len(batch) < self._batch_size:
                try:
                    job = await asyncio.wait_for(
                        self._queue.get(), timeout=self._batch_wait
                    )
                except asyncio.TimeoutError:
                    break
                if job is None:
                    self._queue.task_done()
                    await self._queue.put(None)
                    break
                batch.append(job)

            await self._process_batch(batch)
            for _ in batch:
                self._queue.task_done()

    async def _process_batch(self, jobs: List[QueueJobDTO]) -> None:
        for job in jobs:
            leased = lease(
                job.id, job_type=self._job_type, lease_seconds=job.lease_timeout_seconds
            )
            if leased is None:
                logger.debug(
                    "Matching job %s skipped because it could not be leased", job.id
                )
                continue

            try:
                result = await handle_matching(leased, self._handler_deps)
            except MatchingJobError as exc:
                if not exc.retry and exc.stop_reason:
                    to_dlq(
                        leased.id,
                        job_type=self._job_type,
                        reason=exc.stop_reason,
                        payload=exc.result_payload,
                    )
                    record_activity(
                        "metadata",
                        "matching_job_failed",
                        details={
                            "job_id": leased.id,
                            "error": exc.code,
                            "retry": False,
                            "stop_reason": exc.stop_reason,
                        },
                    )
                else:
                    retry_in = exc.retry_in if exc.retry else None
                    fail(
                        leased.id,
                        job_type=self._job_type,
                        error=exc.code,
                        retry_in=retry_in,
                    )
                    record_activity(
                        "metadata",
                        "matching_job_failed",
                        details={
                            "job_id": leased.id,
                            "error": exc.code,
                            "retry": bool(exc.retry),
                            "retry_in": retry_in,
                        },
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Failed to process matching job %s: %s", leased.id, exc)
                fail(leased.id, job_type=self._job_type, error="internal_error")
                record_activity(
                    "metadata",
                    "matching_job_failed",
                    details={"job_id": leased.id, "error": str(exc)},
                )
            else:
                complete(
                    leased.id,
                    job_type=self._job_type,
                    result_payload=result,
                )

        self._record_heartbeat()

    def _record_heartbeat(self) -> None:
        record_worker_heartbeat("matching")
