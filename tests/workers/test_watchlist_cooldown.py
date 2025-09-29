import types
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import inspect

from app.db import session_scope
from app.models import WatchlistArtist
from app.workers.watchlist_worker import WatchlistFailure, WatchlistWorker
from tests.workers.test_watchlist_worker import (
    StubSoulseek,
    StubSpotify,
    StubSyncWorker,
    _insert_artist,
    _make_config,
)


def _create_worker(**overrides: Any) -> WatchlistWorker:
    spotify = StubSpotify()
    soulseek = StubSoulseek()
    sync_worker = StubSyncWorker()
    config = _make_config(**overrides)
    return WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
    )


def test_cooldown_field_exists_and_index_present() -> None:
    with session_scope() as session:
        engine = session.get_bind()
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("watchlist_artists")}
        assert "retry_block_until" in columns
        indexes = {index["name"] for index in inspector.get_indexes("watchlist_artists")}
        assert "ix_watchlist_retry_block_until" in indexes


@pytest.mark.asyncio
async def test_skip_artist_when_retry_block_until_in_future() -> None:
    future = datetime.utcnow() + timedelta(minutes=30)
    artist_id = _insert_artist(
        "artist-cooldown-skip",
        last_checked=datetime.utcnow() - timedelta(days=1),
        retry_block_until=future,
    )

    worker = _create_worker(retry_budget_per_artist=1, retry_max=1)
    outcomes = await worker.run_once()
    assert outcomes == []

    with session_scope() as session:
        record = session.get(WatchlistArtist, artist_id)
        assert record is not None
        assert record.retry_block_until is not None
        delta_seconds = abs((record.retry_block_until - future).total_seconds())
        assert delta_seconds <= 1


@pytest.mark.asyncio
async def test_set_cooldown_on_budget_exhaustion() -> None:
    artist_id = _insert_artist(
        "artist-cooldown-set",
        last_checked=datetime.utcnow() - timedelta(days=1),
    )

    worker = _create_worker(retry_budget_per_artist=1, retry_max=2, cooldown_minutes=5)

    async def fail_once(self, artist, deadline):  # type: ignore[no-untyped-def]
        raise WatchlistFailure("dependency_error", "boom", retryable=True)

    worker._process_artist_once = types.MethodType(fail_once, worker)

    outcomes = await worker.run_once()
    assert outcomes
    assert outcomes[0].status == "cooldown"

    with session_scope() as session:
        record = session.get(WatchlistArtist, artist_id)
        assert record is not None
        assert record.retry_block_until is not None
        assert record.retry_block_until > datetime.utcnow()


@pytest.mark.asyncio
async def test_clear_cooldown_on_success() -> None:
    past = datetime.utcnow() - timedelta(minutes=10)
    artist_id = _insert_artist(
        "artist-cooldown-clear",
        last_checked=datetime.utcnow() - timedelta(days=1),
        retry_block_until=past,
    )

    worker = _create_worker(retry_budget_per_artist=2, retry_max=1)

    async def succeed(self, artist, deadline):  # type: ignore[no-untyped-def]
        return 0

    worker._process_artist_once = types.MethodType(succeed, worker)

    outcomes = await worker.run_once()
    assert outcomes
    assert outcomes[0].status in {"noop", "ok"}

    with session_scope() as session:
        record = session.get(WatchlistArtist, artist_id)
        assert record is not None
        assert record.retry_block_until is None


@pytest.mark.asyncio
async def test_persistence_across_process_restart() -> None:
    artist_id = _insert_artist(
        "artist-cooldown-persist",
        last_checked=datetime.utcnow() - timedelta(days=1),
    )

    worker = _create_worker(retry_budget_per_artist=1, retry_max=2, cooldown_minutes=15)

    async def fail(self, artist, deadline):  # type: ignore[no-untyped-def]
        raise WatchlistFailure("dependency_error", "boom", retryable=True)

    worker._process_artist_once = types.MethodType(fail, worker)
    await worker.run_once()

    with session_scope() as session:
        record = session.get(WatchlistArtist, artist_id)
        assert record is not None
        first_block = record.retry_block_until
        assert first_block is not None

    fresh_worker = _create_worker(retry_budget_per_artist=1, retry_max=1)
    outcomes = await fresh_worker.run_once()
    assert outcomes == []

    with session_scope() as session:
        record = session.get(WatchlistArtist, artist_id)
        assert record is not None
        assert record.retry_block_until == first_block
