"""Asynchronous dispatcher coordinating orchestrated queue jobs."""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.config import ExternalCallPolicy, OrchestratorConfig, settings
from app.logging import get_logger
from app.orchestrator import events as orchestrator_events
from app.orchestrator.handlers import MatchingJobError
from app.orchestrator.scheduler import Scheduler
from app.workers import persistence

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from app.orchestrator.handlers import (
        MatchingHandlerDeps,
        RetryHandlerDeps,
        SyncHandlerDeps,
        WatchlistHandlerDeps,
    )


JobHandler = Callable[[persistence.QueueJobDTO], Awaitable[Mapping[str, Any] | None]]


def default_handlers(
    sync_deps: "SyncHandlerDeps",
    *,
    matching_deps: "MatchingHandlerDeps" | None = None,
    retry_deps: "RetryHandlerDeps" | None = None,
    watchlist_deps: "WatchlistHandlerDeps" | None = None,
) -> dict[str, JobHandler]:
    """Return the default orchestrator handler mapping."""

    from app.orchestrator.handlers import (
        build_matching_handler,
        build_retry_handler,
        build_sync_handler,
        build_watchlist_handler,
    )

    handlers: dict[str, JobHandler] = {"sync": build_sync_handler(sync_deps)}
    if matching_deps is not None:
        handlers["matching"] = build_matching_handler(matching_deps)
    if retry_deps is not None:
        handlers["retry"] = build_retry_handler(retry_deps)
    if watchlist_deps is not None:
        handlers["watchlist"] = build_watchlist_handler(watchlist_deps)
    return handlers


_DEFAULT_BACKOFF_BASE_MS = 500
_DEFAULT_RETRY_MAX = 3
_DEFAULT_JITTER = 0.2
_MAX_BACKOFF_EXPONENT = 10
_STOP_REASON_MAX_RETRIES = "max_retries_exhausted"


@dataclass(slots=True)
class _PoolLimits:
    global_limit: int
    pool: dict[str, int]


class Dispatcher:
    """Coordinate leased queue jobs and execute handlers with concurrency control."""

    def __init__(
        self,
        scheduler: Scheduler,
        handlers: Mapping[str, JobHandler],
        *,
        orchestrator_config: OrchestratorConfig | None = None,
        external_policy: ExternalCallPolicy | None = None,
        persistence_module=persistence,
        global_concurrency: int | None = None,
        pool_concurrency: Mapping[str, int] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._handlers = {job_type: handler for job_type, handler in handlers.items()}
        self._persistence = persistence_module
        self._logger = get_logger(__name__)
        self._rng = rng or random.Random()
        self._config = orchestrator_config or settings.orchestrator
        self._base_pool_limits = self._config.pool_limits()
        limits = self._resolve_limits(global_concurrency, pool_concurrency)
        self._global_limit = limits.global_limit
        self._global_semaphore = asyncio.Semaphore(self._global_limit)
        self._pool_limits = limits.pool
        self._pool_semaphores: dict[str, asyncio.Semaphore] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._stop_event: asyncio.Event | None = None
        self._pending_stop = False
        self.started: asyncio.Event = asyncio.Event()
        self.stopped: asyncio.Event = asyncio.Event()
        self.stop_requested: bool = False
        policy = external_policy or settings.external
        self._retry_max = max(
            0, policy.retry_max if policy.retry_max is not None else _DEFAULT_RETRY_MAX
        )
        self._backoff_base_ms = max(
            1,
            (
                policy.backoff_base_ms
                if policy.backoff_base_ms is not None
                else _DEFAULT_BACKOFF_BASE_MS
            ),
        )
        jitter_pct = policy.jitter_pct if policy.jitter_pct is not None else _DEFAULT_JITTER
        self._retry_jitter_pct = jitter_pct if jitter_pct >= 0 else 0.0
        self._heartbeat_seconds = max(1.0, float(self._config.heartbeat_s))

    async def run(self, lifespan: asyncio.Event | None = None) -> None:
        """Run the dispatcher loop until a stop signal or lifespan event is set."""

        self._prepare_run_state()
        try:
            self.started.set()
            while not self._should_stop(lifespan):
                leased = self._scheduler.lease_ready_jobs()
                for job in leased:
                    self._start_job(job)
                self._collect_finished_tasks()
                if not leased:
                    await asyncio.sleep(self._scheduler.poll_interval)
        finally:
            if self._stop_event is not None:
                self._stop_event.set()
            if not self.stop_requested:
                self.stop_requested = True
            self.stopped.set()
            await self._await_all_tasks()

    def request_stop(self) -> None:
        """Signal the dispatcher to exit the run loop."""

        self.stop_requested = True
        if self._stop_event is not None and self._stop_event.is_set():
            return
        if self._stop_event is not None:
            self._stop_event.set()
        else:
            self._pending_stop = True

    def _prepare_run_state(self) -> None:
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self._stop_event = asyncio.Event()
        if self._pending_stop:
            self.stop_requested = True
            self._stop_event.set()
            self._pending_stop = False
        else:
            self.stop_requested = False

    def _should_stop(self, lifespan: asyncio.Event | None) -> bool:
        if self._stop_event is not None and self._stop_event.is_set():
            return True
        if lifespan is not None and lifespan.is_set():
            return True
        return False

    def _start_job(self, job: persistence.QueueJobDTO) -> None:
        handler = self._handlers.get(job.type)
        if handler is None:
            orchestrator_events.emit_dlq_event(
                self._logger,
                job_id=job.id,
                job_type=job.type,
                status="missing_handler",
            )
            self._persistence.to_dlq(
                job.id,
                job_type=job.type,
                reason="handler_missing",
                payload=job.payload,
            )
            return

        task = asyncio.create_task(self._execute_job(job, handler))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _execute_job(
        self,
        job: persistence.QueueJobDTO,
        handler: JobHandler,
    ) -> None:
        async with self._acquire_slots(job.type):
            start = time.perf_counter()
            orchestrator_events.emit_dispatch_event(
                self._logger,
                job_id=job.id,
                job_type=job.type,
                status="started",
                attempts=int(job.attempts),
            )
            stop_heartbeat = asyncio.Event()
            heartbeat_task = asyncio.create_task(self._maintain_heartbeat(job, stop_heartbeat))
            try:
                result_payload = await handler(job)
            except MatchingJobError as exc:
                stop_heartbeat.set()
                await self._handle_job_error(job, exc, start)
            except asyncio.CancelledError:
                stop_heartbeat.set()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
                raise
            except Exception as exc:
                stop_heartbeat.set()
                await self._handle_failure(job, exc, start)
            else:
                stop_heartbeat.set()
                await self._handle_success(job, result_payload, start)
            finally:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task

    async def _handle_success(
        self,
        job: persistence.QueueJobDTO,
        result_payload: Mapping[str, Any] | None,
        start: float,
    ) -> None:
        duration_ms = int((time.perf_counter() - start) * 1000)
        self._persistence.complete(
            job.id,
            job_type=job.type,
            result_payload=result_payload,
        )
        orchestrator_events.emit_commit_event(
            self._logger,
            job_id=job.id,
            job_type=job.type,
            status="succeeded",
            attempts=int(job.attempts),
            duration_ms=duration_ms,
        )

    async def _handle_job_error(
        self,
        job: persistence.QueueJobDTO,
        exc: MatchingJobError,
        start: float,
    ) -> None:
        duration_ms = int((time.perf_counter() - start) * 1000)
        attempts = int(job.attempts)
        if exc.retry:
            retry_in = exc.retry_in
            if retry_in is None:
                retry_in = max(1, int(self._calculate_backoff_seconds(attempts)))
            self._persistence.fail(
                job.id,
                job_type=job.type,
                error=exc.code,
                retry_in=retry_in,
            )
            orchestrator_events.emit_commit_event(
                self._logger,
                job_id=job.id,
                job_type=job.type,
                status="retry",
                attempts=attempts,
                duration_ms=duration_ms,
                retry_in=retry_in,
                error=exc.code,
            )
            return

        self._persistence.fail(
            job.id,
            job_type=job.type,
            error=exc.code,
        )
        orchestrator_events.emit_commit_event(
            self._logger,
            job_id=job.id,
            job_type=job.type,
            status="failed",
            attempts=attempts,
            duration_ms=duration_ms,
            error=exc.code,
        )

    async def _handle_failure(
        self,
        job: persistence.QueueJobDTO,
        exc: Exception,
        start: float,
    ) -> None:
        duration_ms = int((time.perf_counter() - start) * 1000)
        message = self._truncate_error(str(exc))
        attempts = int(job.attempts)
        if attempts >= self._retry_max:
            self._persistence.to_dlq(
                job.id,
                job_type=job.type,
                reason=_STOP_REASON_MAX_RETRIES,
                payload={"error": message, "attempts": attempts},
            )
            orchestrator_events.emit_dlq_event(
                self._logger,
                job_id=job.id,
                job_type=job.type,
                status="dead_letter",
                attempts=attempts,
                duration_ms=duration_ms,
                stop_reason=_STOP_REASON_MAX_RETRIES,
                error=message,
            )
            return

        retry_delay = max(1, int(self._calculate_backoff_seconds(attempts)))
        self._persistence.fail(
            job.id,
            job_type=job.type,
            error=message,
            retry_in=retry_delay,
        )
        orchestrator_events.emit_commit_event(
            self._logger,
            job_id=job.id,
            job_type=job.type,
            status="retry",
            attempts=attempts,
            duration_ms=duration_ms,
            retry_in=retry_delay,
            error=message,
        )

    async def _maintain_heartbeat(
        self, job: persistence.QueueJobDTO, stop_signal: asyncio.Event
    ) -> None:
        interval = self._heartbeat_interval(job)
        while True:
            try:
                await asyncio.wait_for(stop_signal.wait(), timeout=interval)
            except asyncio.TimeoutError:
                ok = self._persistence.heartbeat(
                    job.id,
                    job_type=job.type,
                    lease_seconds=job.lease_timeout_seconds,
                )
                if not ok:
                    orchestrator_events.emit_heartbeat_event(
                        self._logger,
                        job_id=job.id,
                        job_type=job.type,
                        status="lost",
                        lease_timeout=int(job.lease_timeout_seconds or 0),
                    )
                continue
            break

    def _heartbeat_interval(self, job: persistence.QueueJobDTO) -> float:
        timeout = max(1, int(job.lease_timeout_seconds or self._config.visibility_timeout_s))
        interval = min(self._heartbeat_seconds, timeout * 0.5)
        return max(1.0, interval)

    def _collect_finished_tasks(self) -> None:
        finished = {task for task in self._tasks if task.done()}
        for task in finished:
            try:
                task.result()
            except asyncio.CancelledError:  # pragma: no cover - cancellation path
                pass
            except Exception:  # pragma: no cover - defensive logging
                self._logger.exception("Unhandled dispatch task error")
        self._tasks.difference_update(finished)

    async def _await_all_tasks(self) -> None:
        if not self._tasks:
            return
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    @contextlib.asynccontextmanager
    async def _acquire_slots(self, job_type: str):
        async with self._global_semaphore:
            pool_sem = self._get_pool_semaphore(job_type)
            async with pool_sem:
                yield

    def _get_pool_semaphore(self, job_type: str) -> asyncio.Semaphore:
        semaphore = self._pool_semaphores.get(job_type)
        if semaphore is not None:
            return semaphore
        limit = self._pool_limits.get(job_type)
        if limit is None:
            limit = self._resolve_pool_limit(job_type)
            self._pool_limits[job_type] = limit
        semaphore = asyncio.Semaphore(limit)
        self._pool_semaphores[job_type] = semaphore
        return semaphore

    def _resolve_limits(
        self,
        global_concurrency: int | None,
        pool_concurrency: Mapping[str, int] | None,
    ) -> _PoolLimits:
        resolved_global = max(1, global_concurrency or self._config.global_concurrency)
        pool: dict[str, int] = {
            name: max(1, limit) for name, limit in self._base_pool_limits.items()
        }
        if pool_concurrency:
            for job_type, limit in pool_concurrency.items():
                pool[job_type] = max(1, int(limit))
        return _PoolLimits(global_limit=resolved_global, pool=pool)

    def _resolve_pool_limit(self, job_type: str) -> int:
        configured = self._base_pool_limits.get(job_type)
        if configured is None:
            configured = self._global_limit
        limit = max(1, configured)
        self._pool_limits[job_type] = limit
        return limit

    def _calculate_backoff_seconds(self, attempts: int) -> float:
        exponent = max(0, min(attempts - 1, _MAX_BACKOFF_EXPONENT))
        base_ms = max(1, self._backoff_base_ms)
        delay_ms = base_ms * (2**exponent)
        if self._retry_jitter_pct:
            jitter = self._rng.uniform(1 - self._retry_jitter_pct, 1 + self._retry_jitter_pct)
        else:
            jitter = 1.0
        return max(0.0, delay_ms * jitter) / 1000.0

    @staticmethod
    def _truncate_error(message: str, limit: int = 512) -> str:
        text = message.strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"


__all__ = ["Dispatcher", "JobHandler", "default_handlers"]
