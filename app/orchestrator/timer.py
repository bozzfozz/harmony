"""Periodic timer for enqueueing watchlist orchestrator jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import contextlib
from dataclasses import dataclass
from datetime import datetime
import inspect
import time

from app.config import WatchlistTimerConfig, WatchlistWorkerConfig, settings
from app.db_async import get_async_sessionmaker
from app.logging import get_logger
from app.orchestrator import events as orchestrator_events
from app.orchestrator.handlers import ARTIST_REFRESH_JOB_TYPE, ARTIST_SCAN_JOB_TYPE
from app.services.artist_workflow_dao import ArtistWorkflowArtistRow, ArtistWorkflowDAO
from app.utils.time import sleep_jitter_ms
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
        dao: ArtistWorkflowDAO | None = None,
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
        resolved_dao = dao or ArtistWorkflowDAO()
        mode = (config.db_io_mode or "thread").strip().lower()
        if mode == "async" and isinstance(resolved_dao, ArtistWorkflowDAO):
            if not resolved_dao.supports_async:
                resolved_dao = resolved_dao.with_async_session_factory(get_async_sessionmaker())
        self._dao = resolved_dao
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
        jitter_value = max(0.0, float(getattr(config, "jitter_pct", 0.0)))
        if jitter_value <= 1:
            self._sleep_jitter_pct = int(round(jitter_value * 100))
        else:
            self._sleep_jitter_pct = int(round(jitter_value))
        self._priority = int(settings.orchestrator.priority_map.get(ARTIST_REFRESH_JOB_TYPE, 0))

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
        except TimeoutError:
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

        stats: _TimerStats | None = None
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
                        "Failed to enqueue watchlist job",
                        extra={"artist_id": artist.id},
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
            try:
                result = callback(enqueued)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                self._logger.exception("Watchlist timer enqueue callback failed")
                stats_for_event = stats or _TimerStats(
                    duration_ms=0,
                    jobs_total=len(enqueued),
                    jobs_enqueued=len(enqueued),
                    jobs_failed=0,
                )
                orchestrator_events.emit_timer_event(
                    self._logger,
                    status="error",
                    component=_LOG_COMPONENT,
                    jobs_total=stats_for_event.jobs_total,
                    jobs_enqueued=stats_for_event.jobs_enqueued,
                    jobs_failed=stats_for_event.jobs_failed,
                    duration_ms=stats_for_event.duration_ms,
                    error="callback_failed",
                )

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
        delay_ms = int(self._interval * 1000)
        sleep_task = asyncio.create_task(
            sleep_jitter_ms(delay_ms, self._sleep_jitter_pct),
            name="watchlist-timer-sleep",
        )
        wait_task = asyncio.create_task(self._stop_event.wait())
        done, pending = await asyncio.wait(
            {sleep_task, wait_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            with contextlib.suppress(asyncio.CancelledError):
                task.result()
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _load_due_artists(self) -> list[ArtistWorkflowArtistRow]:
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

    async def _enqueue_artist(
        self, artist: ArtistWorkflowArtistRow
    ) -> persistence.QueueJobDTO | None:
        payload: dict[str, object] = {"artist_id": int(artist.id)}
        cutoff = artist.last_checked.isoformat() if artist.last_checked else None
        if cutoff:
            payload["cutoff"] = cutoff
        delta_idempotency = f"{ARTIST_SCAN_JOB_TYPE}:{artist.id}:{cutoff or 'never'}"
        payload["delta_idempotency"] = delta_idempotency
        idempotency = f"{ARTIST_REFRESH_JOB_TYPE}:{artist.id}:{cutoff or 'never'}"
        enqueue_async = getattr(self._persistence, "enqueue_async", None)
        if callable(enqueue_async):
            return await enqueue_async(
                ARTIST_REFRESH_JOB_TYPE,
                payload,
                idempotency_key=idempotency,
                priority=self._priority,
            )
        return await asyncio.to_thread(
            self._persistence.enqueue,
            ARTIST_REFRESH_JOB_TYPE,
            payload,
            idempotency_key=idempotency,
            priority=self._priority,
        )


__all__ = ["WatchlistTimer"]
