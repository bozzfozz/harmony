"""Compatibility wrapper seeding orchestrated retry jobs."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from app.logging import get_logger
from app.orchestrator.handlers import enqueue_retry_scan_job

logger = get_logger(__name__)

DEFAULT_SCAN_INTERVAL = 60.0
DEFAULT_BATCH_LIMIT = 100


def _safe_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _safe_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


@dataclass(slots=True)
class RetrySchedulerConfig:
    """Configuration for the retry scheduler cadence."""

    scan_interval: float
    batch_limit: int


def _load_scheduler_config(
    *,
    scan_interval: float | None = None,
    batch_limit: int | None = None,
) -> RetrySchedulerConfig:
    env_interval = _safe_float(os.getenv("RETRY_SCAN_INTERVAL_SEC"), DEFAULT_SCAN_INTERVAL)
    resolved_interval = scan_interval if scan_interval is not None else env_interval
    if resolved_interval <= 0:
        resolved_interval = DEFAULT_SCAN_INTERVAL

    env_batch_limit = _safe_int(os.getenv("RETRY_SCAN_BATCH_LIMIT"), DEFAULT_BATCH_LIMIT)
    resolved_batch = batch_limit if batch_limit is not None else env_batch_limit
    if resolved_batch <= 0:
        resolved_batch = DEFAULT_BATCH_LIMIT

    return RetrySchedulerConfig(scan_interval=resolved_interval, batch_limit=resolved_batch)


class RetryScheduler:
    """Seed orchestrator retry scan jobs based on the configured cadence."""

    def __init__(
        self,
        _sync_worker: Any | None = None,
        *,
        scan_interval: float | None = None,
        batch_limit: int | None = None,
        job_type: str = "retry",
        idempotency_key: str = "retry-scan",
    ) -> None:
        self._config = _load_scheduler_config(
            scan_interval=scan_interval, batch_limit=batch_limit
        )
        self._job_type = job_type
        self._idempotency_key = idempotency_key
        self._lock = asyncio.Lock()
        self._running = False

    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        async with self._lock:
            if self._running:
                return
            await enqueue_retry_scan_job(
                delay_seconds=0.0,
                batch_limit=self._config.batch_limit,
                scan_interval=self._config.scan_interval,
                idempotency_key=self._idempotency_key,
                job_type=self._job_type,
                auto_reschedule=True,
            )
            self._running = True
            logger.info(
                "RetryScheduler seeded orchestrator job",
                extra={
                    "scan_interval": self._config.scan_interval,
                    "batch_limit": self._config.batch_limit,
                },
            )

    async def stop(self) -> None:
        async with self._lock:
            if not self._running:
                return
            await enqueue_retry_scan_job(
                delay_seconds=self._config.scan_interval,
                batch_limit=self._config.batch_limit,
                scan_interval=self._config.scan_interval,
                idempotency_key=self._idempotency_key,
                job_type=self._job_type,
                auto_reschedule=False,
            )
            self._running = False
            logger.info("RetryScheduler stop requested")
