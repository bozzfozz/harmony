from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import WatchlistArtist
from app.services.artist_dao_async import ArtistWatchlistAsyncDAO


pytest.importorskip("aiosqlite")


# pytest-asyncio strict mode requires explicit async fixtures.
@pytest_asyncio.fixture
async def async_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _create_artist(
    session,
    *,
    spotify_id: str,
    name: str,
    priority: int = 0,
    cooldown_s: int = 0,
    last_scan_at: datetime | None = None,
    retry_budget_left: int | None = None,
    retry_block_until: datetime | None = None,
    stop_reason: str | None = None,
) -> int:
    record = WatchlistArtist(
        spotify_artist_id=spotify_id,
        name=name,
        priority=priority,
        cooldown_s=cooldown_s,
        last_scan_at=last_scan_at,
        retry_budget_left=retry_budget_left,
        retry_block_until=retry_block_until,
        stop_reason=stop_reason,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return int(record.id)


@pytest.mark.asyncio
async def test_get_due_orders_by_priority(async_session) -> None:
    now = datetime.utcnow()
    await _create_artist(
        async_session,
        spotify_id="artist-high",
        name="High",
        priority=5,
        cooldown_s=0,
        last_scan_at=now - timedelta(hours=1),
        retry_budget_left=2,
    )
    await _create_artist(
        async_session,
        spotify_id="artist-low",
        name="Low",
        priority=1,
        cooldown_s=0,
        last_scan_at=None,
        retry_budget_left=1,
    )
    await _create_artist(
        async_session,
        spotify_id="artist-blocked",
        name="Blocked",
        priority=10,
        cooldown_s=0,
        last_scan_at=now - timedelta(hours=2),
        retry_budget_left=3,
        retry_block_until=now + timedelta(hours=1),
    )
    await _create_artist(
        async_session,
        spotify_id="artist-budget",
        name="Budget",
        priority=7,
        cooldown_s=0,
        last_scan_at=now - timedelta(hours=3),
        retry_budget_left=0,
    )
    await _create_artist(
        async_session,
        spotify_id="artist-cooldown",
        name="Cooldown",
        priority=8,
        cooldown_s=3_600,
        last_scan_at=now - timedelta(minutes=5),
        retry_budget_left=5,
    )

    dao = ArtistWatchlistAsyncDAO(async_session)
    due = await dao.get_due(3)

    assert [row.spotify_artist_id for row in due] == ["artist-high", "artist-low"]
    assert all(row.retry_budget_left is None or row.retry_budget_left > 0 for row in due)


@pytest.mark.asyncio
async def test_mark_scanned_updates_hash(async_session) -> None:
    artist_id = await _create_artist(
        async_session,
        spotify_id="artist-scan",
        name="Artist",
        last_scan_at=datetime.utcnow() - timedelta(days=1),
        retry_budget_left=1,
    )
    dao = ArtistWatchlistAsyncDAO(async_session)
    assert await dao.mark_scanned(artist_id, "hash-123")

    refreshed = await async_session.get(WatchlistArtist, artist_id)
    assert refreshed is not None
    assert refreshed.last_hash == "hash-123"
    assert refreshed.last_checked is not None
    assert refreshed.last_scan_at is not None
    assert refreshed.updated_at is not None
    assert refreshed.last_scan_at >= refreshed.last_checked - timedelta(seconds=1)


@pytest.mark.asyncio
async def test_bump_cooldown_increases_window(async_session) -> None:
    artist_id = await _create_artist(
        async_session,
        spotify_id="artist-cool",
        name="Artist",
        cooldown_s=900,
        last_scan_at=datetime.utcnow() - timedelta(hours=1),
    )
    dao = ArtistWatchlistAsyncDAO(async_session)
    new_value = await dao.bump_cooldown(artist_id)
    assert new_value == 1_800

    refreshed = await async_session.get(WatchlistArtist, artist_id)
    assert refreshed is not None
    assert refreshed.cooldown_s == 1_800
    assert refreshed.last_scan_at is not None
    assert refreshed.last_checked is not None


@pytest.mark.asyncio
async def test_update_retry_clamps_bounds(async_session) -> None:
    artist_id = await _create_artist(
        async_session,
        spotify_id="artist-retry",
        name="Artist",
        retry_budget_left=3,
    )
    dao = ArtistWatchlistAsyncDAO(async_session)

    assert await dao.update_retry(artist_id, -2) == 1
    assert await dao.update_retry(artist_id, -5) == 0
    assert await dao.update_retry(artist_id, 4) == 4

    refreshed = await async_session.get(WatchlistArtist, artist_id)
    assert refreshed is not None
    assert refreshed.retry_budget_left == 4
