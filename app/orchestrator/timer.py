"""Periodic timer for enqueueing watchlist orchestrator jobs."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from app.config import WatchlistTimerConfig, WatchlistWorkerConfig, settings
from app.logging import get_logger
from app.orchestrator import events as orchestrator_events
from app.services.watchlist_dao import WatchlistArtistRow, WatchlistDAO
from app.workers import persistence

_LOG_COMPONENT = "orchestrator.watchlist_timer"


def _coerce_interval(value: float | int | str | None, default: float) -> float:
    if value is None:
        return default
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return default
    if resolved < 0:
        return 0.0
    return resolved


@dataclass(slots=True)
class _TimerStats:
    duration_ms: int
    jobs_total: int
    jobs_enqueued: int
    jobs_failed: int


class WatchlistTimer:
    """Periodically enqueue orchestrator jobs for watchlist artists."""

    def __init__(
        self,
        *,
        config: WatchlistWorkerConfig,
        timer_config: WatchlistTimerConfig | None = None,
        interval_seconds: float | int | str | None = None,
        enabled: bool | None = None,
        dao: WatchlistDAO | None = None,
        persistence_module=persistence,
        now_factory: Callable[[], datetime] = datetime.utcnow,
        time_source: Callable[[], float] = time.perf_counter,
        on_jobs_enqueued: (
            Callable[[Sequence[persistence.QueueJobDTO]], Awaitable[None] | None] | None
        ) = None,
    ) -> None:
        timer_settings = timer_config or settings.watchlist_timer
        self._config = config
        configured_interval = timer_settings.interval_s
        self._interval = _coerce_interval(
            interval_seconds if interval_seconds is not None else configured_interval,
            configured_interval,
        )
        default_enabled = timer_settings.enabled
        self._enabled = default_enabled if enabled is None else bool(enabled)
        self._dao = dao or WatchlistDAO()
        self._persistence = persistence_module
        self._now_factory = now_factory
        self._time_source = time_source
        self._on_jobs_enqueued = on_jobs_enqueued
        self._logger = get_logger(__name__)
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._shutdown_grace = max(0.0, float(config.shutdown_grace_ms) / 1000.0)
        self._max_per_tick = max(0, int(config.max_per_tick))
        mode = (config.db_io_mode or "thread").strip().lower()
        self._db_mode = "async" if mode == "async" else "thread"

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def is_running(self) -> bool:
        task = self._task
        return bool(task and not task.done())

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    async def start(self) -> bool:
        """Start the background timer task if enabled."""

        if not self._enabled:
            return False
        if self.is_running:
            return False
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="watchlist-timer")
        return True

    async def stop(self) -> None:
        """Signal the timer to stop and await task completion."""

        self._stop_event.set()
        task = self._task
        if task is None:
            return
        timeout = self._shutdown_grace if self._shutdown_grace > 0 else 0.0
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        finally:
            self._task = None

    async def trigger(self) -> list[persistence.QueueJobDTO]:
        """Execute a single timer tick, returning enqueued job DTOs."""

        if not self._enabled:
            orchestrator_events.emit_timer_event(
                self._logger,
                status="disabled",
                component=_LOG_COMPONENT,
                jobs_total=0,
                jobs_enqueued=0,
                jobs_failed=0,
                duration_ms=0,
            )
            return []

        if self._lock.locked():
            orchestrator_events.emit_timer_event(
                self._logger,
                status="skipped",
                component=_LOG_COMPONENT,
                reason="busy",
                jobs_total=0,
                jobs_enqueued=0,
                jobs_failed=0,
                duration_ms=0,
            )
            return []

        async with self._lock:
            start = self._time_source()
            try:
                artists = await self._load_due_artists()
            except Exception:  # pragma: no cover - defensive logging
                duration_ms = int((self._time_source() - start) * 1000)
                self._logger.exception("Failed to load watchlist artists for timer")
                orchestrator_events.emit_timer_event(
                    self._logger,
                    status="error",
                    component=_LOG_COMPONENT,
                    error="load_failed",
                    jobs_total=0,
                    jobs_enqueued=0,
                    jobs_failed=0,
                    duration_ms=duration_ms,
                )
                return []

            if not artists:
                duration_ms = int((self._time_source() - start) * 1000)
                orchestrator_events.emit_timer_event(
                    self._logger,
                    status="idle",
                    component=_LOG_COMPONENT,
                    jobs_total=0,
                    jobs_enqueued=0,
                    jobs_failed=0,
                    duration_ms=duration_ms,
                )
                return []

            enqueued: list[persistence.QueueJobDTO] = []
            failures = 0
            for artist in artists:
                try:
                    job = await self._enqueue_artist(artist)
                except Exception:  # pragma: no cover - defensive logging
                    failures += 1
                    self._logger.exception(
                        "Failed to enqueue watchlist job", extra={"artist_id": artist.id}
                    )
                    continue
                if job is not None:
                    enqueued.append(job)
            duration_ms = int((self._time_source() - start) * 1000)
            stats = _TimerStats(
                duration_ms=duration_ms,
                jobs_total=len(artists),
                jobs_enqueued=len(enqueued),
                jobs_failed=failures,
            )
            status = "ok" if failures == 0 else "partial"
            orchestrator_events.emit_timer_event(
                self._logger,
                status=status,
                component=_LOG_COMPONENT,
                jobs_total=stats.jobs_total,
                jobs_enqueued=stats.jobs_enqueued,
                jobs_failed=stats.jobs_failed,
                duration_ms=stats.duration_ms,
            )

        if enqueued and self._on_jobs_enqueued is not None:
            callback = self._on_jobs_enqueued
            result = callback(enqueued)
            if inspect.isawaitable(result):
                await result

        return enqueued

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                await self.trigger()
                if self._stop_event.is_set():
                    break
                await self._sleep_until_next()
        except asyncio.CancelledError:  # pragma: no cover - task lifecycle
            raise

    async def _sleep_until_next(self) -> None:
        if self._interval <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
        except asyncio.TimeoutError:
            return

    async def _load_due_artists(self) -> list[WatchlistArtistRow]:
        if self._max_per_tick <= 0:
            return []
        cutoff = self._now_factory()
        if self._db_mode == "async":
            result = self._dao.load_batch(self._max_per_tick, cutoff=cutoff)
            if inspect.isawaitable(result):
                return list(await result)
            return list(result)
        return await asyncio.to_thread(
            self._dao.load_batch,
            self._max_per_tick,
            cutoff=cutoff,
        )

    async def _enqueue_artist(self, artist: WatchlistArtistRow) -> persistence.QueueJobDTO | None:
        payload: dict[str, object] = {"artist_id": int(artist.id)}
        cutoff = artist.last_checked.isoformat() if artist.last_checked else None
        if cutoff:
            payload["cutoff"] = cutoff
        idempotency = f"watchlist:{artist.id}:{cutoff or 'never'}"
        return await asyncio.to_thread(
            self._persistence.enqueue,
            "watchlist",
            payload,
            idempotency_key=idempotency,
        )


__all__ = ["WatchlistTimer"]
