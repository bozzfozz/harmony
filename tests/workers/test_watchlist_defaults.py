from datetime import datetime, timedelta

import pytest

from app.config import load_config
from app.services.watchlist_dao import WatchlistDAO
from app.workers import watchlist_worker
from app.workers.watchlist_worker import WatchlistWorker
from tests.workers.test_watchlist_worker import (
    StubSoulseek,
    StubSpotify,
    StubSyncWorker,
    _insert_artist,
    _make_config,
)


def test_defaults_loaded_and_clamped(monkeypatch):
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


@pytest.mark.asyncio
async def test_concurrency_does_not_exceed_max():
    for index in range(6):
        _insert_artist(
            f"artist-concurrency-{index}",
            last_checked=datetime.utcnow() - timedelta(days=1),
        )

    spotify = StubSpotify()
    soulseek = StubSoulseek(delay=0.05)
    soulseek.search_results = [
        {
            "username": "tester",
            "files": [{"filename": "Tester - Track.flac", "priority": 0}],
        }
    ]
    for index in range(6):
        artist_id = f"artist-concurrency-{index}"
        album_id = f"album-{index}"
        track_id = f"track-{index}"
        spotify.artist_albums[artist_id] = [
            {
                "id": album_id,
                "name": f"Release {index}",
                "artists": [{"name": f"Tester {index}"}],
                "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
                "release_date_precision": "day",
            }
        ]
        spotify.album_tracks[album_id] = [
            {
                "id": track_id,
                "name": f"Track {index}",
                "artists": [{"name": f"Tester {index}"}],
            }
        ]

    sync_worker = StubSyncWorker()
    config = _make_config(
        max_concurrency=3,
        retry_max=1,
        retry_budget_per_artist=6,
        max_per_tick=6,
    )
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.1,
        dao=WatchlistDAO(),
    )

    outcomes = await worker.run_once()
    assert len(outcomes) == 6
    assert soulseek.max_active <= 3


@pytest.mark.asyncio
async def test_timeouts_cancel_external_calls():
    _insert_artist(
        "artist-timeout-defaults",
        last_checked=datetime.utcnow() - timedelta(days=1),
    )

    spotify = StubSpotify()
    spotify.fail_album_calls = 1
    spotify.album_timeout_delay = 0.2
    spotify.artist_albums["artist-timeout-defaults"] = [
        {
            "id": "album-timeout-defaults",
            "name": "Timeout",
            "artists": [{"name": "Tester"}],
            "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "release_date_precision": "day",
        }
    ]

    soulseek = StubSoulseek()
    soulseek.search_results = []
    sync_worker = StubSyncWorker()
    config = _make_config(spotify_timeout_ms=50, retry_max=1)
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.05,
        dao=WatchlistDAO(),
    )

    outcomes = await worker.run_once()
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.status == "timeout"
    assert outcome.attempts == 1


@pytest.mark.asyncio
async def test_retry_stops_after_retry_max_per_operation():
    _insert_artist(
        "artist-retry-max",
        last_checked=datetime.utcnow() - timedelta(days=1),
    )

    spotify = StubSpotify()
    spotify.artist_albums["artist-retry-max"] = [
        {
            "id": "album-retry-max",
            "name": "Retry",
            "artists": [{"name": "Tester"}],
            "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "release_date_precision": "day",
        }
    ]
    spotify.album_tracks["album-retry-max"] = [
        {
            "id": "track-retry-max",
            "name": "Retry",
            "artists": [{"name": "Tester"}],
        }
    ]

    soulseek = StubSoulseek(delay=0.2)
    sync_worker = StubSyncWorker()
    config = _make_config(
        retry_max=2,
        retry_budget_per_artist=6,
        slskd_search_timeout_ms=50,
    )
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.05,
        dao=WatchlistDAO(),
    )

    outcomes = await worker.run_once()
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.status == "timeout"
    assert outcome.attempts == 2
    assert len(soulseek.queries) == 2


class FrozenDatetime(datetime):
    current = datetime(2024, 1, 1, 12, 0, 0)

    @classmethod
    def utcnow(cls):
        return cls.current

    @classmethod
    def advance(cls, delta: timedelta):
        cls.current = cls.current + delta


@pytest.mark.asyncio
async def test_artist_retry_budget_and_cooldown_enforced(monkeypatch):
    monkeypatch.setattr(watchlist_worker, "datetime", FrozenDatetime)
    monkeypatch.setattr("app.services.watchlist_dao.datetime", FrozenDatetime)

    FrozenDatetime.current = datetime(2024, 1, 1, 12, 0, 0)

    _insert_artist(
        "artist-budget",
        last_checked=FrozenDatetime.current - timedelta(days=1),
    )

    spotify = StubSpotify()
    spotify.artist_albums["artist-budget"] = [
        {
            "id": "album-budget",
            "name": "Budget",
            "artists": [{"name": "Tester"}],
            "release_date": FrozenDatetime.current.strftime("%Y-%m-%d"),
            "release_date_precision": "day",
        }
    ]
    spotify.album_tracks["album-budget"] = [
        {
            "id": "track-budget",
            "name": "Budget",
            "artists": [{"name": "Tester"}],
        }
    ]

    soulseek = StubSoulseek(delay=0.2)
    sync_worker = StubSyncWorker()
    config = _make_config(
        retry_max=5,
        retry_budget_per_artist=2,
        slskd_search_timeout_ms=50,
        cooldown_minutes=1,
    )
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.05,
        dao=WatchlistDAO(),
    )

    first_outcomes = await worker.run_once()
    assert len(first_outcomes) == 1
    first = first_outcomes[0]
    assert first.status == "cooldown"
    assert first.attempts == 2
    assert len(soulseek.queries) == 2

    FrozenDatetime.advance(timedelta(minutes=2))
    spotify.artist_albums["artist-budget"][0]["release_date"] = (
        FrozenDatetime.current + timedelta(days=1)
    ).strftime("%Y-%m-%d")

    second_outcomes = await worker.run_once()
    assert len(second_outcomes) == 1
    second = second_outcomes[0]
    assert second.status == "cooldown"
    assert second.attempts == 2
    assert len(soulseek.queries) == 4

    dao = WatchlistDAO()
    artists = dao.load_batch(1, cutoff=FrozenDatetime.current + timedelta(minutes=10))
    assert artists
    assert artists[0].spotify_artist_id == "artist-budget"
