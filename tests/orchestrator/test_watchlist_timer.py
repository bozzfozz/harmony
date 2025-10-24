"""Tests for the watchlist orchestrator timer."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest

from app.config import WatchlistWorkerConfig
from app.orchestrator import events as orchestrator_events, timer as timer_module
from app.orchestrator.handlers import ARTIST_REFRESH_JOB_TYPE, ARTIST_SCAN_JOB_TYPE
from app.orchestrator.timer import WatchlistTimer
from app.services.artist_workflow_dao import ArtistWorkflowArtistRow


@dataclass(slots=True)
class FakeQueueJob:
    """Minimal queue job DTO used for assertions."""

    id: int
    type: str
    payload: dict[str, Any]
    priority: int
    idempotency_key: str | None
    attempts: int = 0


class FakePersistenceModule:
    """Persistence stub capturing enqueue requests."""

    def __init__(self) -> None:
        self.enqueued: list[FakeQueueJob] = []
        self._counter = 0

    async def enqueue_async(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None,
        priority: int,
    ) -> FakeQueueJob:
        self._counter += 1
        job = FakeQueueJob(
            id=self._counter,
            type=job_type,
            payload=dict(payload),
            priority=priority,
            idempotency_key=idempotency_key,
        )
        self.enqueued.append(job)
        return job


class FakeWorkflowDAO:
    """DAO stub returning predetermined batches of artists."""

    def __init__(self, batches: Iterable[Iterable[ArtistWorkflowArtistRow]]) -> None:
        self._batches = [list(batch) for batch in batches]
        self.calls: list[dict[str, Any]] = []

    async def load_batch(
        self, limit: int, *, cutoff: datetime | None
    ) -> list[ArtistWorkflowArtistRow]:
        self.calls.append({"limit": limit, "cutoff": cutoff})
        if self._batches:
            return list(self._batches.pop(0))
        return []


@pytest.fixture()
def timer_events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture orchestrator timer events for assertions."""

    captured: list[dict[str, Any]] = []

    def _capture(
        logger: Any,
        *,
        status: str,
        duration_ms: int,
        jobs_total: int,
        jobs_enqueued: int,
        jobs_failed: int,
        component: str | None = None,
        reason: str | None = None,
        error: str | None = None,
    ) -> None:
        captured.append(
            {
                "status": status,
                "duration_ms": duration_ms,
                "jobs_total": jobs_total,
                "jobs_enqueued": jobs_enqueued,
                "jobs_failed": jobs_failed,
                "component": component,
                "reason": reason,
                "error": error,
            }
        )

    monkeypatch.setattr(orchestrator_events, "emit_timer_event", _capture)
    return captured


def make_worker_config(**overrides: Any) -> WatchlistWorkerConfig:
    defaults = {
        "max_concurrency": 4,
        "max_per_tick": 10,
        "spotify_timeout_ms": 1000,
        "slskd_search_timeout_ms": 1000,
        "tick_budget_ms": 1000,
        "backoff_base_ms": 100,
        "retry_max": 3,
        "jitter_pct": 0.0,
        "shutdown_grace_ms": 0,
        "db_io_mode": "async",
        "retry_budget_per_artist": 5,
        "cooldown_minutes": 15,
    }
    defaults.update(overrides)
    return WatchlistWorkerConfig(**defaults)


@pytest.mark.asyncio
async def test_start_stop_idempotent() -> None:
    dao = FakeWorkflowDAO([])
    persistence = FakePersistenceModule()
    timer = WatchlistTimer(
        config=make_worker_config(),
        enabled=True,
        interval_seconds=0,
        dao=dao,
        persistence_module=persistence,
    )

    first_start = await timer.start()
    assert first_start is True
    first_task = timer.task
    assert first_task is not None and not first_task.done()

    second_start = await timer.start()
    assert second_start is False
    assert timer.task is first_task

    await timer.stop()
    assert timer.task is None

    # Second stop call should be a no-op.
    await timer.stop()


@pytest.mark.asyncio
async def test_trigger_emits_disabled_event_when_disabled(
    timer_events: list[dict[str, Any]],
) -> None:
    dao = FakeWorkflowDAO([])
    persistence = FakePersistenceModule()
    timer = WatchlistTimer(
        config=make_worker_config(),
        enabled=False,
        interval_seconds=0,
        dao=dao,
        persistence_module=persistence,
    )

    jobs = await timer.trigger()

    assert jobs == []
    assert dao.calls == []
    assert timer_events == [
        {
            "status": "disabled",
            "duration_ms": 0,
            "jobs_total": 0,
            "jobs_enqueued": 0,
            "jobs_failed": 0,
            "component": "orchestrator.watchlist_timer",
            "reason": None,
            "error": None,
        }
    ]


@pytest.mark.asyncio
async def test_trigger_idle_when_no_artists(timer_events: list[dict[str, Any]]) -> None:
    dao = FakeWorkflowDAO([[]])
    persistence = FakePersistenceModule()
    timer = WatchlistTimer(
        config=make_worker_config(),
        enabled=True,
        interval_seconds=0,
        dao=dao,
        persistence_module=persistence,
    )

    jobs = await timer.trigger()

    assert jobs == []
    assert len(dao.calls) == 1
    assert timer_events[-1]["status"] == "idle"
    assert timer_events[-1]["jobs_total"] == 0
    assert timer_events[-1]["jobs_enqueued"] == 0


@pytest.mark.asyncio
async def test_trigger_enqueues_jobs_and_invokes_callback(
    timer_events: list[dict[str, Any]],
) -> None:
    artist_with_cutoff = ArtistWorkflowArtistRow(
        id=1,
        spotify_artist_id="sp-1",
        name="Artist One",
        last_checked=datetime(2024, 1, 1, 12, 0, 0),
        retry_block_until=None,
    )
    artist_without_cutoff = ArtistWorkflowArtistRow(
        id=2,
        spotify_artist_id="sp-2",
        name="Artist Two",
        last_checked=None,
        retry_block_until=None,
    )
    dao = FakeWorkflowDAO([[artist_with_cutoff, artist_without_cutoff]])
    persistence = FakePersistenceModule()
    callback_called = asyncio.Event()
    received_jobs: list[list[FakeQueueJob]] = []

    async def on_jobs_enqueued(jobs: list[FakeQueueJob]) -> None:
        received_jobs.append(list(jobs))
        callback_called.set()

    timer = WatchlistTimer(
        config=make_worker_config(),
        enabled=True,
        interval_seconds=0,
        dao=dao,
        persistence_module=persistence,
        on_jobs_enqueued=on_jobs_enqueued,
    )

    jobs = await timer.trigger()
    await asyncio.wait_for(callback_called.wait(), timeout=1)

    assert len(jobs) == 2
    assert persistence.enqueued == jobs
    assert received_jobs == [jobs]

    first_job = persistence.enqueued[0]
    assert first_job.type == ARTIST_REFRESH_JOB_TYPE
    assert first_job.payload["artist_id"] == artist_with_cutoff.id
    assert first_job.payload["cutoff"] == artist_with_cutoff.last_checked.isoformat()
    expected_delta = (
        f"{ARTIST_SCAN_JOB_TYPE}:{artist_with_cutoff.id}:"
        f"{artist_with_cutoff.last_checked.isoformat()}"
    )
    assert first_job.payload["delta_idempotency"] == expected_delta

    second_job = persistence.enqueued[1]
    assert second_job.payload["artist_id"] == artist_without_cutoff.id
    assert "cutoff" not in second_job.payload

    assert timer_events[-1]["status"] == "ok"
    assert timer_events[-1]["jobs_total"] == 2
    assert timer_events[-1]["jobs_enqueued"] == 2
    assert timer_events[-1]["jobs_failed"] == 0


@pytest.mark.asyncio
async def test_trigger_emits_error_event_when_callback_fails(
    timer_events: list[dict[str, Any]],
) -> None:
    artist = ArtistWorkflowArtistRow(
        id=1,
        spotify_artist_id="sp-1",
        name="Artist",
        last_checked=None,
        retry_block_until=None,
    )
    dao = FakeWorkflowDAO([[artist]])
    persistence = FakePersistenceModule()

    async def failing_callback(jobs: list[FakeQueueJob]) -> None:
        raise RuntimeError("boom")

    timer = WatchlistTimer(
        config=make_worker_config(),
        enabled=True,
        interval_seconds=0,
        dao=dao,
        persistence_module=persistence,
        on_jobs_enqueued=failing_callback,
    )

    jobs = await timer.trigger()

    assert len(jobs) == 1
    assert len(timer_events) == 2
    assert timer_events[-2]["status"] == "ok"
    assert timer_events[-1]["status"] == "error"
    assert timer_events[-1]["error"] == "callback_failed"
    assert timer_events[-1]["jobs_total"] == 1
    assert timer_events[-1]["jobs_enqueued"] == 1


@pytest.mark.asyncio
async def test_trigger_skips_when_lock_contended(timer_events: list[dict[str, Any]]) -> None:
    dao = FakeWorkflowDAO(
        [
            [
                ArtistWorkflowArtistRow(
                    id=1,
                    spotify_artist_id="sp-1",
                    name="Artist",
                    last_checked=None,
                    retry_block_until=None,
                )
            ]
        ]
    )
    persistence = FakePersistenceModule()
    timer = WatchlistTimer(
        config=make_worker_config(),
        enabled=True,
        interval_seconds=0,
        dao=dao,
        persistence_module=persistence,
    )

    await timer._lock.acquire()
    try:
        jobs = await timer.trigger()
    finally:
        timer._lock.release()

    assert jobs == []
    assert dao.calls == []
    assert timer_events[-1]["status"] == "skipped"
    assert timer_events[-1]["reason"] == "busy"


@pytest.mark.asyncio
async def test_sleep_until_next_uses_configured_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    dao = FakeWorkflowDAO([])
    persistence = FakePersistenceModule()
    timer = WatchlistTimer(
        config=make_worker_config(jitter_pct=0.15),
        enabled=True,
        interval_seconds=1.5,
        dao=dao,
        persistence_module=persistence,
    )

    calls: list[tuple[int, int]] = []

    async def fake_sleep(ms: int, jitter_pct: int) -> float:
        calls.append((ms, jitter_pct))
        await asyncio.sleep(0)
        return 0.0

    monkeypatch.setattr(timer_module, "sleep_jitter_ms", fake_sleep)

    await timer._sleep_until_next()

    assert calls == [(1500, 15)]


@pytest.mark.asyncio
async def test_stop_waits_for_enqueue_callback_within_grace(
    timer_events: list[dict[str, Any]],
) -> None:
    artist = ArtistWorkflowArtistRow(
        id=1,
        spotify_artist_id="sp-1",
        name="Artist",
        last_checked=datetime(2024, 1, 1, 12, 0, 0),
        retry_block_until=None,
    )
    dao = FakeWorkflowDAO([[artist], []])
    persistence = FakePersistenceModule()
    callback_started = asyncio.Event()
    callback_finished = asyncio.Event()

    async def on_jobs_enqueued(jobs: list[FakeQueueJob]) -> None:
        callback_started.set()
        await asyncio.sleep(0.05)
        callback_finished.set()

    timer = WatchlistTimer(
        config=make_worker_config(shutdown_grace_ms=200),
        enabled=True,
        interval_seconds=0,
        dao=dao,
        persistence_module=persistence,
        on_jobs_enqueued=on_jobs_enqueued,
    )

    await timer.start()
    try:
        await asyncio.wait_for(callback_started.wait(), timeout=1)
        await timer.stop()
    finally:
        await timer.stop()

    assert callback_finished.is_set()
    assert timer.task is None
    assert timer_events[-1]["status"] in {"ok", "partial"}


@pytest.mark.asyncio
async def test_stop_cancels_enqueue_callback_after_grace_timeout() -> None:
    artist = ArtistWorkflowArtistRow(
        id=1,
        spotify_artist_id="sp-1",
        name="Artist",
        last_checked=datetime(2024, 1, 1, 12, 0, 0),
        retry_block_until=None,
    )
    dao = FakeWorkflowDAO([[artist], []])
    persistence = FakePersistenceModule()
    callback_started = asyncio.Event()
    callback_cancelled = asyncio.Event()

    async def on_jobs_enqueued(jobs: list[FakeQueueJob]) -> None:
        callback_started.set()
        try:
            await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            callback_cancelled.set()
            raise

    timer = WatchlistTimer(
        config=make_worker_config(shutdown_grace_ms=50),
        enabled=True,
        interval_seconds=0,
        dao=dao,
        persistence_module=persistence,
        on_jobs_enqueued=on_jobs_enqueued,
    )

    await timer.start()
    try:
        await asyncio.wait_for(callback_started.wait(), timeout=1)
        await timer.stop()
    finally:
        await timer.stop()

    await asyncio.wait_for(callback_cancelled.wait(), timeout=1)
    assert timer.task is None
