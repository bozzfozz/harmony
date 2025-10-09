import asyncio
from datetime import datetime
from itertools import count
from types import SimpleNamespace

import pytest

from app.config import WatchlistWorkerConfig
from app.models import QueueJobStatus
from app.orchestrator import timer as timer_module
from app.orchestrator.handlers import ARTIST_REFRESH_JOB_TYPE, ARTIST_SCAN_JOB_TYPE
from app.orchestrator.timer import WatchlistTimer
from app.services.artist_workflow_dao import ArtistWorkflowArtistRow
from app.workers import persistence


class RecordingDAO:
    def __init__(self, rows):
        self.rows = list(rows)
        self.args = None

    def load_batch(self, limit: int, *, cutoff: datetime):
        self.args = (limit, cutoff)
        return self.rows[:limit]


def test_artist_row_defaults_last_hash_to_none() -> None:
    row = ArtistWorkflowArtistRow(
        id=42,
        spotify_artist_id="artist-42",
        name="Artist",
        last_checked=None,
        retry_block_until=None,
    )

    assert row.last_hash is None


def test_artist_row_normalizes_blank_last_hash() -> None:
    row = ArtistWorkflowArtistRow(
        id=7,
        spotify_artist_id="artist-7",
        name="Artist",
        last_checked=None,
        retry_block_until=None,
        last_hash="   ",
    )

    assert row.last_hash is None


def _build_config(**overrides) -> WatchlistWorkerConfig:
    params = {
        "max_concurrency": 3,
        "max_per_tick": overrides.get("max_per_tick", 2),
        "spotify_timeout_ms": 8_000,
        "slskd_search_timeout_ms": 12_000,
        "tick_budget_ms": 8_000,
        "backoff_base_ms": 250,
        "retry_max": 3,
        "jitter_pct": 0.2,
        "shutdown_grace_ms": overrides.get("shutdown_grace_ms", 200),
        "db_io_mode": overrides.get("db_io_mode", "async"),
        "retry_budget_per_artist": 6,
        "cooldown_minutes": 15,
    }
    return WatchlistWorkerConfig(**params)


@pytest.mark.asyncio
async def test_trigger_enqueues_due_artists(monkeypatch):
    async def immediate_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(timer_module.asyncio, "to_thread", immediate_to_thread)

    logged: list[tuple[str, dict[str, object]]] = []

    def fake_log(logger, event, **meta):
        logged.append((event, meta))

    monkeypatch.setattr("app.orchestrator.events.log_event", fake_log)
    monkeypatch.setattr(
        "app.orchestrator.events.increment_counter", lambda *args, **kwargs: 0
    )

    artists = [
        ArtistWorkflowArtistRow(
            id=1,
            spotify_artist_id="a1",
            name="Artist 1",
            last_checked=None,
            retry_block_until=None,
        ),
        ArtistWorkflowArtistRow(
            id=2,
            spotify_artist_id="a2",
            name="Artist 2",
            last_checked=datetime(2023, 1, 1, 10, 0, 0),
            retry_block_until=None,
        ),
    ]

    dao = RecordingDAO(artists)

    fake_time = SimpleNamespace(value=0.0)

    def time_source() -> float:
        return fake_time.value

    now_value = datetime(2023, 1, 1, 12, 0, 0)

    job_ids = count(1)

    def fake_enqueue(
        job_type: str,
        payload: dict[str, object],
        *,
        idempotency_key: str,
        priority: int,
    ):
        assert job_type == ARTIST_REFRESH_JOB_TYPE
        fake_time.value += 0.05
        job = persistence.QueueJobDTO(
            id=next(job_ids),
            type=job_type,
            payload=dict(payload),
            priority=priority,
            attempts=0,
            available_at=now_value,
            lease_expires_at=None,
            status=QueueJobStatus.PENDING,
            idempotency_key=idempotency_key,
        )
        return job

    persistence_module = SimpleNamespace(enqueue=fake_enqueue)

    timer = WatchlistTimer(
        config=_build_config(),
        dao=dao,
        persistence_module=persistence_module,
        now_factory=lambda: now_value,
        time_source=time_source,
    )

    enqueued = await timer.trigger()

    assert len(enqueued) == 2
    assert dao.args[0] == 2
    assert dao.args[1] == now_value
    payloads = [job.payload for job in enqueued]
    assert payloads[0] == {
        "artist_id": 1,
        "delta_idempotency": f"{ARTIST_SCAN_JOB_TYPE}:1:never",
    }
    assert payloads[1] == {
        "artist_id": 2,
        "cutoff": "2023-01-01T10:00:00",
        "delta_idempotency": f"{ARTIST_SCAN_JOB_TYPE}:2:2023-01-01T10:00:00",
    }
    keys = [job.idempotency_key for job in enqueued]
    assert keys == [
        f"{ARTIST_REFRESH_JOB_TYPE}:1:never",
        f"{ARTIST_REFRESH_JOB_TYPE}:2:2023-01-01T10:00:00",
    ]

    assert logged
    event_name, meta = logged[-1]
    assert event_name == "orchestrator.timer_tick"
    assert meta["status"] == "ok"
    assert meta["jobs_total"] == 2
    assert meta["jobs_enqueued"] == 2
    assert meta["jobs_failed"] == 0
    expected_duration = int(fake_time.value * 1000)
    assert meta["duration_ms"] == expected_duration


@pytest.mark.asyncio
async def test_trigger_disabled_logs(monkeypatch):
    async def immediate_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(timer_module.asyncio, "to_thread", immediate_to_thread)

    events: list[dict[str, object]] = []

    def capture_log(logger, event, **meta):
        events.append(meta)

    monkeypatch.setattr("app.orchestrator.events.log_event", capture_log)
    monkeypatch.setattr(
        "app.orchestrator.events.increment_counter", lambda *args, **kwargs: 0
    )

    timer = WatchlistTimer(config=_build_config(), enabled=False, dao=RecordingDAO([]))

    result = await timer.trigger()

    assert result == []
    assert events[-1]["status"] == "disabled"


@pytest.mark.asyncio
async def test_trigger_skips_when_busy(monkeypatch):
    async def immediate_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(timer_module.asyncio, "to_thread", immediate_to_thread)

    captured: list[dict[str, object]] = []

    def capture_log(logger, event, **meta):
        captured.append(meta)

    monkeypatch.setattr("app.orchestrator.events.log_event", capture_log)
    monkeypatch.setattr(
        "app.orchestrator.events.increment_counter", lambda *args, **kwargs: 0
    )

    timer = WatchlistTimer(config=_build_config(), dao=RecordingDAO([]))

    await timer._lock.acquire()
    try:
        result = await timer.trigger()
    finally:
        timer._lock.release()

    assert result == []
    assert captured[-1]["status"] == "skipped"
    assert captured[-1]["reason"] == "busy"


@pytest.mark.asyncio
async def test_start_stop_lifecycle(monkeypatch):
    async def immediate_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(timer_module.asyncio, "to_thread", immediate_to_thread)

    timer = WatchlistTimer(
        config=_build_config(shutdown_grace_ms=50),
        dao=RecordingDAO([]),
    )

    started = asyncio.Event()
    stopped = asyncio.Event()

    async def fake_run(self):
        started.set()
        await self._stop_event.wait()
        stopped.set()

    monkeypatch.setattr(WatchlistTimer, "_run", fake_run, raising=False)

    assert await timer.start() is True
    await asyncio.wait_for(started.wait(), timeout=0.2)
    assert timer.is_running

    await timer.stop()
    await asyncio.wait_for(stopped.wait(), timeout=0.2)
    assert not timer.is_running
    assert timer.task is None
