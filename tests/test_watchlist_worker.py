from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.config import WatchlistWorkerConfig
from app.db import session_scope
from app.models import Download, WatchlistArtist
from app.services.watchlist_dao import WatchlistDAO
from app.workers.watchlist_worker import WatchlistWorker


class StubSpotify:
    def __init__(self) -> None:
        self.artist_albums: dict[str, list[dict[str, Any]]] = {}
        self.album_tracks: dict[str, list[dict[str, Any]]] = {}

    def get_artist_albums(self, artist_id: str) -> list[dict[str, Any]]:
        return list(self.artist_albums.get(artist_id, []))

    def get_album_tracks(self, album_id: str) -> list[dict[str, Any]]:
        return list(self.album_tracks.get(album_id, []))


class StubSoulseek:
    def __init__(self, *, delay: float = 0.0) -> None:
        self.delay = delay
        self.search_results: list[dict[str, Any]] = []
        self.queries: list[str] = []

    async def search(self, query: str) -> list[dict[str, Any]]:
        self.queries.append(query)
        if self.delay:
            await asyncio.sleep(self.delay)
        return list(self.search_results)


class HangingSoulseek(StubSoulseek):
    def __init__(self) -> None:
        super().__init__(delay=0.0)
        self._event = asyncio.Event()

    async def search(self, query: str) -> list[dict[str, Any]]:  # type: ignore[override]
        self.queries.append(query)
        await self._event.wait()
        return list(self.search_results)

    def release(self) -> None:
        self._event.set()


class StubSyncWorker:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    async def enqueue(self, job: dict[str, Any]) -> None:
        self.jobs.append(job)


def _default_config(**overrides: Any) -> WatchlistWorkerConfig:
    config = WatchlistWorkerConfig(
        concurrency=overrides.get("concurrency", 2),
        max_per_tick=overrides.get("max_per_tick", 5),
        search_timeout_ms=overrides.get("search_timeout_ms", 500),
        tick_budget_ms=overrides.get("tick_budget_ms", 1_000),
        backoff_base_ms=overrides.get("backoff_base_ms", 200),
        backoff_max_tries=overrides.get("backoff_max_tries", 2),
        jitter_pct=overrides.get("jitter_pct", 0.0),
        shutdown_grace_ms=overrides.get("shutdown_grace_ms", 200),
    )
    return config


def _insert_artist(spotify_artist_id: str, *, last_checked: datetime | None = None) -> int:
    with session_scope() as session:
        artist = WatchlistArtist(
            spotify_artist_id=spotify_artist_id,
            name="Watcher",
            last_checked=last_checked,
        )
        session.add(artist)
        session.flush()
        return int(artist.id)


@pytest.mark.asyncio
async def test_watchlist_worker_processes_artist_successfully() -> None:
    artist_id = _insert_artist("artist-watch", last_checked=datetime.utcnow() - timedelta(days=2))

    spotify = StubSpotify()
    spotify.artist_albums["artist-watch"] = [
        {
            "id": "album-new",
            "name": "Brand New",
            "artists": [{"name": "Watcher"}],
            "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "release_date_precision": "day",
        }
    ]
    spotify.album_tracks["album-new"] = [
        {
            "id": "track-new",
            "name": "Fresh Cut",
            "artists": [{"name": "Watcher"}],
        }
    ]

    soulseek = StubSoulseek()
    soulseek.search_results = [
        {
            "username": "watcher-user",
            "files": [
                {
                    "filename": "Watcher - Fresh Cut - Brand New.flac",
                    "priority": 0,
                }
            ],
        }
    ]
    sync_worker = StubSyncWorker()
    config = _default_config(max_per_tick=3, tick_budget_ms=5_000)
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.1,
        dao=WatchlistDAO(),
    )

    outcomes = await worker.run_once()
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.artist.id == artist_id
    assert outcome.status == "ok"
    assert outcome.queued == 1

    with session_scope() as session:
        download = session.execute(
            select(Download).where(Download.spotify_track_id == "track-new")
        ).scalar_one()
        assert download.request_payload["filename"].startswith("Watcher - Fresh Cut")
        refreshed = session.get(WatchlistArtist, artist_id)
        assert refreshed is not None
        assert refreshed.last_checked is not None
        assert refreshed.last_checked > datetime.utcnow() - timedelta(minutes=5)

    assert len(sync_worker.jobs) == 1
    assert soulseek.queries[0].startswith("Watcher")


@pytest.mark.asyncio
async def test_watchlist_worker_applies_backoff_on_timeout() -> None:
    artist_id = _insert_artist("artist-timeout", last_checked=datetime.utcnow() - timedelta(days=1))

    spotify = StubSpotify()
    spotify.artist_albums["artist-timeout"] = [
        {
            "id": "album-timeout",
            "name": "Slow Burn",
            "artists": [{"name": "Watcher"}],
            "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "release_date_precision": "day",
        }
    ]
    spotify.album_tracks["album-timeout"] = [
        {
            "id": "track-timeout",
            "name": "Wait",  # noqa: RUF100
            "artists": [{"name": "Watcher"}],
        }
    ]

    soulseek = StubSoulseek(delay=0.2)
    sync_worker = StubSyncWorker()
    config = _default_config(
        search_timeout_ms=50, backoff_base_ms=150, backoff_max_tries=2, tick_budget_ms=2_000
    )
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.1,
        dao=WatchlistDAO(),
    )

    before = datetime.utcnow()
    outcomes = await worker.run_once()
    outcome = outcomes[0]
    assert outcome.status == "timeout"
    assert outcome.queued == 0
    assert outcome.attempts == config.backoff_max_tries

    with session_scope() as session:
        refreshed = session.get(WatchlistArtist, artist_id)
        assert refreshed is not None
        assert refreshed.last_checked is not None
        assert refreshed.last_checked >= before + timedelta(milliseconds=140)


@pytest.mark.asyncio
async def test_watchlist_worker_stop_is_cancel_safe() -> None:
    artist_id = _insert_artist("artist-cancel", last_checked=datetime.utcnow() - timedelta(days=3))

    spotify = StubSpotify()
    spotify.artist_albums["artist-cancel"] = [
        {
            "id": "album-cancel",
            "name": "Endless",
            "artists": [{"name": "Watcher"}],
            "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "release_date_precision": "day",
        }
    ]
    spotify.album_tracks["album-cancel"] = [
        {
            "id": "track-cancel",
            "name": "Hold",
            "artists": [{"name": "Watcher"}],
        }
    ]

    soulseek = HangingSoulseek()
    sync_worker = StubSyncWorker()
    config = _default_config(search_timeout_ms=5_000, backoff_max_tries=1, shutdown_grace_ms=100)
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.05,
        dao=WatchlistDAO(),
    )

    await worker.start()
    await asyncio.sleep(0.1)
    await worker.stop()

    assert worker._task is None  # noqa: SLF001 - inspected for test stability
    assert len(sync_worker.jobs) == 0

    with session_scope() as session:
        refreshed = session.get(WatchlistArtist, artist_id)
        assert refreshed is not None
        # Cancellation should not advance the timestamp beyond "now".
        assert refreshed.last_checked is None or refreshed.last_checked <= datetime.utcnow()

    soulseek.release()
