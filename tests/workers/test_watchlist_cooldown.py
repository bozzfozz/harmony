from __future__ import annotations

from datetime import datetime, timedelta
import pytest
from sqlalchemy import inspect

from app.db import session_scope
from app.models import WatchlistArtist
from app.services.artist_workflow_dao import ArtistWorkflowDAO
from app.workers.watchlist_worker import WatchlistWorker
from tests.workers.test_watchlist_worker import _insert_artist, _make_config


def test_cooldown_field_exists_and_index_present() -> None:
    with session_scope() as session:
        engine = session.get_bind()
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("watchlist_artists")}
        assert "retry_block_until" in columns
        indexes = {index["name"] for index in inspector.get_indexes("watchlist_artists")}
        assert "ix_watchlist_retry_block_until" in indexes


@pytest.mark.asyncio
async def test_worker_skips_artists_with_active_cooldown() -> None:
    future = datetime.utcnow() + timedelta(minutes=30)
    artist_id = _insert_artist(
        "artist-cooldown-skip",
        last_checked=datetime.utcnow() - timedelta(days=1),
        retry_block_until=future,
    )

    worker = WatchlistWorker(
        config=_make_config(max_per_tick=1),
        interval_seconds=0.01,
        dao=ArtistWorkflowDAO(),
    )
    outcomes = await worker.run_once()
    assert outcomes == []

    with session_scope() as session:
        record = session.get(WatchlistArtist, artist_id)
        assert record is not None
        assert record.retry_block_until is not None
        assert record.retry_block_until == future
