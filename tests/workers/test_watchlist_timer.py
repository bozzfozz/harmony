"""Tests for the watchlist orchestrator timer behaviour."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.config import WatchlistWorkerConfig
from app.db import session_scope
from app.models import QueueJob
from app.orchestrator.timer import WatchlistTimer
from app.services.artist_workflow_dao import ArtistWorkflowArtistRow


class _StubWatchlistDAO:
    def __init__(self, artists: list[ArtistWorkflowArtistRow]) -> None:
        self._artists = artists
        self.calls = 0

    def load_batch(self, limit: int, *, cutoff: datetime | None = None):
        self.calls += 1
        return list(self._artists[:limit])


class _BlockingWatchlistDAO:
    def __init__(self, artists: list[ArtistWorkflowArtistRow], gate: asyncio.Event) -> None:
        self._artists = artists
        self._gate = gate
        self.started = asyncio.Event()

    async def load_batch(self, limit: int, *, cutoff: datetime | None = None):
        self.started.set()
        await self._gate.wait()
        return list(self._artists[:limit])


def _timer_config() -> WatchlistWorkerConfig:
    return WatchlistWorkerConfig(
        max_concurrency=3,
        max_per_tick=5,
        spotify_timeout_ms=1000,
        slskd_search_timeout_ms=1000,
        tick_budget_ms=1000,
        backoff_base_ms=100,
        retry_max=3,
        jitter_pct=0.0,
        shutdown_grace_ms=0,
        db_io_mode="async",
        retry_budget_per_artist=3,
        cooldown_minutes=0,
    )


@pytest.mark.asyncio
async def test_watchlist_timer_enqueues_idempotently(monkeypatch: pytest.MonkeyPatch) -> None:
    artist = ArtistWorkflowArtistRow(
        id=101,
        spotify_artist_id="artist-101",
        name="Test Artist",
        last_checked=None,
        retry_block_until=None,
    )
    dao = _StubWatchlistDAO([artist])

    async def immediate_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        return func(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", immediate_to_thread)

    timer = WatchlistTimer(
        config=_timer_config(),
        interval_seconds=0,
        dao=dao,
        now_factory=lambda: datetime(2024, 1, 1, 0, 0, 0),
        time_source=lambda: 0.0,
    )

    first = await timer.trigger()
    second = await timer.trigger()

    assert first and first[0].payload["artist_id"] == 101
    assert second and second[0].id == first[0].id
    assert dao.calls == 2

    with session_scope() as session:
        jobs = session.query(QueueJob).filter(QueueJob.type == "artist_refresh").all()
        assert len(jobs) == 1


@pytest.mark.asyncio
async def test_watchlist_timer_skips_reentrant_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    artist = ArtistWorkflowArtistRow(
        id=202,
        spotify_artist_id="artist-202",
        name="Artist",
        last_checked=None,
        retry_block_until=None,
    )
    gate = asyncio.Event()
    dao = _BlockingWatchlistDAO([artist], gate)

    async def immediate_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        return func(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", immediate_to_thread)

    timer = WatchlistTimer(
        config=_timer_config(),
        interval_seconds=0,
        dao=dao,
        now_factory=lambda: datetime(2024, 1, 1, 0, 0, 0),
        time_source=lambda: 0.0,
    )

    first_task = asyncio.create_task(timer.trigger())
    await dao.started.wait()
    second = await timer.trigger()
    assert second == []
    gate.set()
    first_result = await first_task
    assert first_result and first_result[0].payload["artist_id"] == 202
