"""Asynchronous worker responsible for executing Spotify backfill jobs."""

from __future__ import annotations

import asyncio
from typing import Optional

from app.logging import get_logger
from app.services.backfill_service import BackfillJobSpec, BackfillService
from app.utils.activity import record_worker_started, record_worker_stopped
from app.utils.events import WORKER_STOPPED
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat

logger = get_logger(__name__)


class BackfillWorker:
    """Queue based worker executing backfill jobs sequentially."""

    def __init__(self, service: BackfillService) -> None:
        self._service = service
        self._queue: asyncio.Queue[BackfillJobSpec] | None = None
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._queue = asyncio.Queue()
        self._loop = asyncio.get_running_loop()
        self._running = True
        record_worker_started("spotify_backfill")
        mark_worker_status("spotify_backfill", "running")
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        was_running = self._running
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:  # pragma: no cover - cancellation path
                pass
            except RuntimeError:  # pragma: no cover - cross-loop teardown guard
                logger.debug("BackfillWorker stop awaited on foreign event loop")
            self._task = None
        mark_worker_status("spotify_backfill", WORKER_STOPPED)
        if was_running:
            record_worker_stopped("spotify_backfill")
        self._queue = None
        self._loop = None

    async def enqueue(self, job: BackfillJobSpec) -> None:
        if self._queue is None:
            self._queue = asyncio.Queue()
        await self._queue.put(job)
        record_worker_heartbeat("spotify_backfill")

    async def wait_until_idle(self) -> None:
        if self._queue is None:
            return
        await self._queue.join()

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self) -> None:
        logger.info("BackfillWorker started")
        record_worker_heartbeat("spotify_backfill")
        queue = self._queue or asyncio.Queue()
        self._queue = queue
        try:
            while self._running:
                try:
                    job = await queue.get()
                except asyncio.CancelledError:  # pragma: no cover - cancellation lifecycle
                    raise

                try:
                    await self._service.execute(job)
                except Exception:  # pragma: no cover - defensive logging
                    logger.exception("Backfill job failed", extra={"job_id": job.id})
                finally:
                    queue.task_done()
                    record_worker_heartbeat("spotify_backfill")
        except asyncio.CancelledError:  # pragma: no cover - cancellation lifecycle
            logger.debug("BackfillWorker cancelled")
            raise
        finally:
            self._running = False
            logger.info("BackfillWorker stopped")


__all__ = ["BackfillWorker"]
