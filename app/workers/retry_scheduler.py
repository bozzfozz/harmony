"""Periodic scheduler that re-enqueues failed downloads when due."""

from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import select

from app.db import session_scope
from app.logging import get_logger
from app.models import Download
from app.utils.events import DOWNLOAD_RETRY_FAILED
from app.utils.activity import record_activity
from app.workers.sync_worker import (
    RetryConfig,
    SyncWorker,
    _calculate_backoff_seconds,
    _load_retry_config,
    _safe_float,
    _safe_int,
    _truncate_error,
)

logger = get_logger(__name__)

DEFAULT_SCAN_INTERVAL = 60.0
DEFAULT_BATCH_LIMIT = 100


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
    """Background task that scans for downloads ready to retry."""

    def __init__(
        self,
        sync_worker: SyncWorker,
        *,
        scan_interval: float | None = None,
        batch_limit: int | None = None,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._worker = sync_worker
        self._scheduler_config = _load_scheduler_config(
            scan_interval=scan_interval, batch_limit=batch_limit
        )
        self._retry_config = retry_config or _load_retry_config()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._running = asyncio.Event()
        self._rng = random.Random()

    def is_running(self) -> bool:
        return self._running.is_set()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await self._task
        finally:
            self._task = None

    async def _run(self) -> None:
        logger.info("RetryScheduler started")
        self._running.set()
        try:
            while True:
                await self._scan_and_enqueue()
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._scheduler_config.scan_interval
                    )
                except asyncio.TimeoutError:
                    if self._stop_event.is_set():
                        break
                    continue
                if self._stop_event.is_set():
                    break
        finally:
            self._running.clear()
            logger.info("RetryScheduler stopped")

    async def _scan_and_enqueue(self) -> None:
        now = datetime.utcnow()
        jobs: List[Dict[str, Any]] = []
        with session_scope() as session:
            stmt = (
                select(Download)
                .where(
                    Download.state == "failed",
                    Download.next_retry_at.is_not(None),
                    Download.next_retry_at <= now,
                    Download.retry_count <= self._retry_config.max_attempts,
                )
                .order_by(Download.next_retry_at.asc())
                .limit(self._scheduler_config.batch_limit)
            )
            records = session.execute(stmt).scalars().all()
            for record in records:
                payload = dict(record.request_payload or {})
                file_info = payload.get("file")
                if not isinstance(file_info, dict):
                    record.state = "dead_letter"
                    record.next_retry_at = None
                    record.last_error = _truncate_error("missing request payload for retry")
                    session.add(record)
                    logger.warning(
                        "event=retry_dead_letter download_id=%s retry_count=%s result=dead_letter",
                        record.id,
                        record.retry_count,
                    )
                    continue

                username = payload.get("username") or record.username
                if not username:
                    record.state = "dead_letter"
                    record.next_retry_at = None
                    record.last_error = _truncate_error("missing username for retry")
                    session.add(record)
                    logger.warning(
                        "event=retry_dead_letter download_id=%s retry_count=%s result=dead_letter",
                        record.id,
                        record.retry_count,
                    )
                    continue

                file_payload = dict(file_info)
                file_payload["download_id"] = record.id
                priority = SyncWorker._coerce_priority(
                    file_payload.get("priority") or payload.get("priority") or record.priority
                )
                if "priority" not in file_payload:
                    file_payload["priority"] = priority

                jobs.append(
                    {
                        "download_id": record.id,
                        "retry_count": record.retry_count,
                        "job": {
                            "username": username,
                            "files": [file_payload],
                            "priority": priority,
                        },
                    }
                )

                record.state = "queued"
                record.next_retry_at = None
                record.updated_at = now
                session.add(record)
                logger.info(
                    "event=retry_claim download_id=%s retry_count=%s result=claimed",
                    record.id,
                    record.retry_count,
                )

        for entry in jobs:
            download_id = int(entry["download_id"])
            job_payload = entry["job"]
            try:
                await self._worker.enqueue(job_payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(
                    "event=retry_enqueue download_id=%s result=error error=%s",
                    download_id,
                    exc,
                )
                retry_error = _truncate_error(str(exc))
                with session_scope() as session:
                    record = session.get(Download, download_id)
                    if record is None:
                        continue
                    record.state = "failed"
                    record.last_error = retry_error
                    delay = _calculate_backoff_seconds(
                        int(record.retry_count or 0), self._retry_config, self._rng
                    )
                    record.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                    record.updated_at = datetime.utcnow()
                    session.add(record)
                record_activity(
                    "download",
                    DOWNLOAD_RETRY_FAILED,
                    details={
                        "downloads": [
                            {
                                "download_id": download_id,
                                "retry_count": entry.get("retry_count"),
                            }
                        ],
                        "error": retry_error,
                        "username": job_payload.get("username"),
                    },
                )
