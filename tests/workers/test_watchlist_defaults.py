from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import load_config
from app.db import session_scope
from app.models import QueueJob, WatchlistArtist
from app.services.artist_workflow_dao import ArtistWorkflowDAO
from app.workers.watchlist_worker import WatchlistWorker
from tests.workers.test_watchlist_worker import _insert_artist, _make_config


def test_defaults_loaded_and_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    overrides = {
        "WATCHLIST_MAX_CONCURRENCY": "-5",
        "WATCHLIST_SPOTIFY_TIMEOUT_MS": "50",
        "WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS": "90000",
        "WATCHLIST_RETRY_MAX": "0",
        "WATCHLIST_BACKOFF_BASE_MS": "8000",
        "WATCHLIST_RETRY_BUDGET_PER_ARTIST": "0",
        "WATCHLIST_COOLDOWN_MINUTES": "-10",
        "WATCHLIST_DB_IO_MODE": "ASYNC",
        "WATCHLIST_MAX_PER_TICK": "500",
        "WATCHLIST_JITTER_PCT": "2",
    }
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)

    config = load_config().watchlist

    assert config.max_concurrency == 1
    assert config.spotify_timeout_ms == 100
    assert config.slskd_search_timeout_ms == 60_000
    assert config.retry_max == 1
    assert config.backoff_base_ms == 5_000
    assert config.retry_budget_per_artist == 1
    assert config.cooldown_minutes == 0
    assert config.db_io_mode == "async"
    assert config.max_per_tick == 100
    assert config.jitter_pct == 1.0


def test_watchlist_cooldown_and_retry_budget_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/harmony"
    )
    monkeypatch.setenv("ARTIST_COOLDOWN_S", "59")
    monkeypatch.setenv("ARTIST_MAX_RETRY_PER_ARTIST", "25")
    monkeypatch.setenv("WATCHLIST_COOLDOWN_MINUTES", "5")
    monkeypatch.setenv("WATCHLIST_RETRY_BUDGET_PER_ARTIST", "2")

    config = load_config().watchlist

    assert config.cooldown_minutes == 1
    assert config.retry_budget_per_artist == 20


@pytest.mark.asyncio
async def test_worker_enqueues_due_artists() -> None:
    for index in range(3):
        _insert_artist(
            f"artist-enqueue-{index}",
            last_checked=datetime.utcnow() - timedelta(days=1),
        )

    worker = WatchlistWorker(
        config=_make_config(max_per_tick=5),
        interval_seconds=0.01,
        dao=ArtistWorkflowDAO(),
    )

    outcomes = await worker.run_once()
    assert len(outcomes) == 3
    assert all(outcome.enqueued for outcome in outcomes)

    with session_scope() as session:
        jobs = (
            session.execute(select(QueueJob).where(QueueJob.type == "artist_refresh"))
            .scalars()
            .all()
        )
        assert len(jobs) == 3
        keys = {job.idempotency_key for job in jobs}
        assert len(keys) == 3


@pytest.mark.asyncio
async def test_worker_idempotency_prevents_duplicates() -> None:
    artist_id = _insert_artist(
        "artist-idempotent",
        last_checked=datetime.utcnow() - timedelta(days=1),
    )

    worker = WatchlistWorker(
        config=_make_config(max_per_tick=1),
        interval_seconds=0.01,
        dao=ArtistWorkflowDAO(),
    )

    first_run = await worker.run_once()
    second_run = await worker.run_once()

    assert len(first_run) == 1
    assert len(second_run) == 1
    assert first_run[0].enqueued
    assert second_run[0].enqueued

    with session_scope() as session:
        jobs = (
            session.execute(select(QueueJob).where(QueueJob.type == "artist_refresh"))
            .scalars()
            .all()
        )
        assert len(jobs) == 1
        job = jobs[0]
        assert job.idempotency_key is not None
        artist = session.get(WatchlistArtist, artist_id)
        assert artist is not None
        # Running twice should not create additional jobs.
        assert job.payload.get("artist_id") == artist_id
