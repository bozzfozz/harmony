"""Queue orchestration scheduler for Harmony background workers."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import OrchestratorConfig, settings
from app.logging import get_logger
from app.orchestrator import events as orchestrator_events
from app.workers import persistence


@dataclass(slots=True)
class PriorityConfig:
    """Configuration for orchestrator job type polling priorities."""

    priorities: dict[str, int]

    @classmethod
    def from_config(cls, config: OrchestratorConfig) -> "PriorityConfig":
        return cls(priorities=dict(config.priority_map))

    @classmethod
    def from_env(
        cls, env: Mapping[str, Any] | None = None
    ) -> "PriorityConfig":  # pragma: no cover - compatibility shim
        if env is None:
            return cls.from_config(settings.orchestrator)
        return cls(priorities=OrchestratorConfig.from_env(env).priority_map)

    @property
    def job_types(self) -> tuple[str, ...]:
        """Return configured job types ordered by configured priority."""

        return tuple(
            sorted(
                self.priorities.keys(),
                key=lambda item: (-self.priorities[item], item),
            )
        )

    def get(self, job_type: str, default: int = 0) -> int:
        return self.priorities.get(job_type, default)


class Scheduler:
    """Asynchronous queue scheduler orchestrating worker leases."""

    def __init__(
        self,
        *,
        config: OrchestratorConfig | None = None,
        priority_config: PriorityConfig | None = None,
        poll_interval_ms: int | None = None,
        visibility_timeout: int | None = None,
        persistence_module=persistence,
    ) -> None:
        self._config = config or settings.orchestrator
        self._priority = priority_config or PriorityConfig.from_config(self._config)
        poll_ms = (
            poll_interval_ms if poll_interval_ms is not None else self._config.poll_interval_ms
        )
        timeout_s = (
            visibility_timeout
            if visibility_timeout is not None
            else self._config.visibility_timeout_s
        )
        self._poll_interval = max(0.0, poll_ms / 1000.0)
        self._visibility_timeout = max(1, timeout_s)
        self._persistence = persistence_module
        self._logger = get_logger(__name__)
        self._stop_signal: asyncio.Event | None = None
        self._pending_stop = False
        self.started: asyncio.Event = asyncio.Event()
        self.stopped: asyncio.Event = asyncio.Event()
        self.stop_requested: bool = False

    @property
    def poll_interval(self) -> float:
        """Return the currently configured polling interval in seconds."""

        return self._poll_interval

    def request_stop(self) -> None:
        self.stop_requested = True
        if self._stop_signal is not None:
            self._stop_signal.set()
        else:
            self._pending_stop = True

    async def run(self, lifespan: asyncio.Event | None = None) -> None:
        """Run the scheduler loop until a stop or lifespan signal triggers."""

        self._prepare_run_state()
        try:
            self.started.set()
            while not self._should_stop(lifespan):
                await self._tick()
                await self._sleep(lifespan)
        finally:
            if self._stop_signal is not None:
                self._stop_signal.set()
            if not self.stop_requested:
                self.stop_requested = True
            self.stopped.set()

    def _prepare_run_state(self) -> None:
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self._stop_signal = asyncio.Event()
        if self._pending_stop:
            self.stop_requested = True
            self._stop_signal.set()
            self._pending_stop = False
        else:
            self.stop_requested = False

    def _should_stop(self, lifespan: asyncio.Event | None) -> bool:
        if self._stop_signal is not None and self._stop_signal.is_set():
            return True
        if lifespan is not None and lifespan.is_set():
            return True
        return False

    async def _tick(self) -> None:
        self.lease_ready_jobs()

    def lease_ready_jobs(self) -> list[persistence.QueueJobDTO]:
        """Lease and return jobs that are ready for processing."""

        jobs = self._collect_ready_jobs()
        leased_jobs: list[persistence.QueueJobDTO] = []
        for job in jobs:
            orchestrator_events.emit_schedule_event(
                self._logger,
                job_id=job.id,
                job_type=job.type,
                attempts=int(job.attempts),
                priority=int(job.priority),
                available_at=orchestrator_events.format_datetime(job.available_at),
            )
            leased = self._persistence.lease(
                job.id,
                job_type=job.type,
                lease_seconds=self._visibility_timeout,
            )
            status = "leased" if leased is not None else "skipped"
            orchestrator_events.emit_lease_event(
                self._logger,
                job_id=job.id,
                job_type=job.type,
                status=status,
                priority=int(job.priority),
                lease_timeout=self._visibility_timeout,
            )
            if leased is not None:
                leased_jobs.append(leased)
        return leased_jobs

    def _collect_ready_jobs(self) -> list[persistence.QueueJobDTO]:
        ready: list[persistence.QueueJobDTO] = []
        job_types = self._priority.job_types or ("sync",)
        for job_type in job_types:
            fetched = self._persistence.fetch_ready(job_type)
            if not fetched:
                continue
            ready.extend(fetched)
        ready.sort(key=self._job_sort_key)
        return ready

    @staticmethod
    def _job_sort_key(job: persistence.QueueJobDTO) -> tuple[int, datetime, int]:
        return (-int(job.priority), job.available_at, int(job.id))

    async def _sleep(self, lifespan: asyncio.Event | None) -> None:
        timeout = self._poll_interval
        if timeout <= 0:
            await asyncio.sleep(0)
            return

        waiters: list[asyncio.Task[None]] = []
        if lifespan is not None:
            waiters.append(asyncio.create_task(lifespan.wait()))
        if self._stop_signal is not None:
            waiters.append(asyncio.create_task(self._stop_signal.wait()))
        try:
            if waiters:
                done, pending = await asyncio.wait(
                    waiters,
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    with contextlib.suppress(asyncio.CancelledError):
                        task.result()
                for task in pending:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            else:
                await asyncio.sleep(timeout)
        finally:
            for task in waiters:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task


__all__ = ["PriorityConfig", "Scheduler"]
