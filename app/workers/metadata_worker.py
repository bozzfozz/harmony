"""Worker that coordinates metadata refresh operations for the dashboard."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict

from app.logging import get_logger
from app.workers.scan_worker import ScanWorker

logger = get_logger(__name__)


class MetadataUpdateRunningError(RuntimeError):
    """Raised when a metadata update is already running."""


class MetadataUpdateWorker:
    """Trigger on-demand metadata refreshes using existing workers."""

    def __init__(
        self,
        scan_worker: ScanWorker,
        matching_worker: Any | None = None,
    ) -> None:
        self._scan_worker = scan_worker
        self._matching_worker = matching_worker
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._stop_requested = False
        self._state: Dict[str, Any] = {
            "status": "idle",
            "phase": "Idle",
            "processed": 0,
            "matching_queue": 0,
            "started_at": None,
            "completed_at": None,
            "error": None,
        }

    async def start(self) -> Dict[str, Any]:
        """Begin a new metadata update cycle."""

        async with self._lock:
            if self._task and not self._task.done():
                raise MetadataUpdateRunningError()

            self._stop_requested = False
            self._state.update(
                status="running",
                phase="Preparing",
                processed=0,
                error=None,
                started_at=datetime.now(timezone.utc),
                completed_at=None,
            )
            logger.info("Metadata update started")
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._run())
            return self._snapshot()

    async def stop(self) -> Dict[str, Any]:
        """Request graceful shutdown of the current metadata update."""

        if self._task and not self._task.done():
            self._stop_requested = True
            self._state.update(status="stopping", phase="Stopping current task")
            logger.info("Stop requested for metadata update")
        return self._snapshot()

    def status(self) -> Dict[str, Any]:
        """Return a serialisable view of the current state."""

        return self._snapshot()

    async def _run(self) -> None:
        try:
            await self._scan_phase()
            if self._stop_requested:
                self._finish("stopped", "Stopped by user")
                return
            await self._matching_phase()
            if self._stop_requested:
                self._finish("stopped", "Stopped by user")
                return
            self._finish("completed", "Completed")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Metadata update failed: %s", exc)
            self._state.update(
                status="error",
                phase="Error",
                error=str(exc),
                completed_at=datetime.now(timezone.utc),
            )
        finally:
            self._task = None
            self._stop_requested = False

    async def _scan_phase(self) -> None:
        self._state.update(phase="Scanning library")
        await self._scan_worker.run_once()
        self._state["processed"] += 1

    async def _matching_phase(self) -> None:
        self._state.update(phase="Reconciling matches")
        queue = getattr(self._matching_worker, "queue", None)
        queue_size = 0
        if queue is not None and hasattr(queue, "qsize"):
            try:
                queue_size = int(queue.qsize())
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug("Unable to inspect matching queue: %s", exc)
        self._state["matching_queue"] = max(queue_size, 0)
        await asyncio.sleep(0)

    def _finish(self, status: str, phase: str) -> None:
        self._state.update(
            status=status,
            phase=phase,
            completed_at=datetime.now(timezone.utc),
        )
        logger.info("Metadata update finished with status %s", status)

    def _snapshot(self) -> Dict[str, Any]:
        state = dict(self._state)
        for key in ("started_at", "completed_at"):
            value = state.get(key)
            if isinstance(value, datetime):
                state[key] = value.isoformat()
            elif value is None:
                state[key] = None
        return state

