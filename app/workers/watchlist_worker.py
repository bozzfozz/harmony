from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime
import time

from app.config import WatchlistWorkerConfig, settings
from app.db_async import get_async_sessionmaker
from app.logging import get_logger
from app.logging_events import log_event
from app.services.artist_workflow_dao import ArtistWorkflowArtistRow, ArtistWorkflowDAO
from app.utils.activity import record_worker_started, record_worker_stopped
from app.utils.events import WORKER_STOPPED
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat
from app.workers import persistence

logger = get_logger(__name__)

DEFAULT_INTERVAL_SECONDS = 86_400.0
MIN_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class WatchlistEnqueueResult:
    """Outcome for a single watchlist enqueue attempt."""

    artist: ArtistWorkflowArtistRow
    enqueued: bool
    reason: str | None = None


class WatchlistWorker:
    """Periodically enqueue orchestrator jobs for watchlist artists."""

    def __init__(
        self,
        *,
        config: WatchlistWorkerConfig,
        interval_seconds: float | None = None,
        dao: ArtistWorkflowDAO | None = None,
    ) -> None:
        self._config = config
        interval = float(interval_seconds or DEFAULT_INTERVAL_SECONDS)
        self._interval = max(interval, MIN_INTERVAL_SECONDS)
        resolved_dao = dao or ArtistWorkflowDAO()
        mode = (config.db_io_mode or "thread").strip().lower()
        if mode == "async" and isinstance(resolved_dao, ArtistWorkflowDAO):
            if not resolved_dao.supports_async:
                resolved_dao = resolved_dao.with_async_session_factory(get_async_sessionmaker())
        self._dao = resolved_dao
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._tick_budget_seconds = max(self._config.tick_budget_ms, 0) / 1000.0
        self._priority = int(settings.orchestrator.priority_map.get("artist_refresh", 0))

        log_event(
            logger,
            "worker.config",
            component="worker.watchlist",
            status="ok",
            interval_s=int(self._interval),
            max_per_tick=self._config.max_per_tick,
        )

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if self._running:
            return
        self._running = True
        self._stop_event = asyncio.Event()
        record_worker_started("watchlist")
        mark_worker_status("watchlist", "running")
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        was_running = self._running
        self._running = False
        self._stop_event.set()
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(task), timeout=self._config.shutdown_grace_ms / 1000.0
                )
            except asyncio.TimeoutError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            finally:
                self._task = None
        mark_worker_status("watchlist", WORKER_STOPPED)
        if was_running or task is not None:
            record_worker_stopped("watchlist")

    async def run_once(self) -> list[WatchlistEnqueueResult]:
        """Execute a single enqueue cycle (primarily for tests)."""

        return await self._enqueue_due_artists()

    async def _run(self) -> None:
        log_event(
            logger,
            "worker.start",
            component="worker.watchlist",
            status="running",
            interval_s=int(self._interval),
            max_per_tick=self._config.max_per_tick,
        )
        try:
            while self._running and not self._stop_event.is_set():
                await self._enqueue_due_artists()
                if self._stop_event.is_set():
                    break
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:  # pragma: no cover - lifecycle management
            raise
        finally:
            running = self._running
            self._running = False
            if running:
                mark_worker_status("watchlist", WORKER_STOPPED)
                record_worker_stopped("watchlist")
            log_event(
                logger,
                "worker.stop",
                component="worker.watchlist",
                status="stopped",
            )

    async def _enqueue_due_artists(self) -> list[WatchlistEnqueueResult]:
        record_worker_heartbeat("watchlist")
        start = time.monotonic()
        deadline = start + self._tick_budget_seconds if self._tick_budget_seconds else None
        now = datetime.utcnow()
        artists = await asyncio.to_thread(
            self._dao.load_batch,
            self._config.max_per_tick,
            cutoff=now,
        )
        if not artists:
            log_event(
                logger,
                "worker.tick",
                component="worker.watchlist",
                status="idle",
                duration_ms=int((time.monotonic() - start) * 1000),
                jobs_total=0,
            )
            return []

        outcomes: list[WatchlistEnqueueResult] = []
        for artist in artists:
            if deadline is not None and time.monotonic() >= deadline:
                break
            success = await self._enqueue_artist_job(artist)
            outcomes.append(
                WatchlistEnqueueResult(
                    artist=artist,
                    enqueued=success,
                    reason=None if success else "enqueue_failed",
                )
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        log_event(
            logger,
            "worker.tick",
            component="worker.watchlist",
            status="ok",
            duration_ms=duration_ms,
            jobs_total=len(outcomes),
            jobs_success=sum(1 for outcome in outcomes if outcome.enqueued),
        )
        return outcomes

    async def _enqueue_artist_job(self, artist: ArtistWorkflowArtistRow) -> bool:
        cutoff = artist.last_checked.isoformat() if artist.last_checked else None
        payload = {"artist_id": int(artist.id)}
        if cutoff:
            payload["cutoff"] = cutoff
        delta_idempotency = f"artist-delta:{artist.id}:{cutoff or 'never'}"
        payload["delta_idempotency"] = delta_idempotency
        idempotency_key = f"artist-refresh:{artist.id}:{cutoff or 'never'}"
        try:
            await asyncio.to_thread(
                persistence.enqueue,
                "artist_refresh",
                payload,
                idempotency_key=idempotency_key,
                priority=self._priority,
            )
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "event=artist.start status=error artist_id=%s", artist.spotify_artist_id
            )
            return False

        log_event(
            logger,
            "artist.start",
            component="worker.watchlist",
            status="queued",
            entity_id=artist.spotify_artist_id,
            job_idempotency=idempotency_key,
        )
        return True


__all__ = ["WatchlistWorker", "WatchlistEnqueueResult"]
