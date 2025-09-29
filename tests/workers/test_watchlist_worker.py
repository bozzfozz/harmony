import asyncio
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Sequence

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
        self.fail_album_calls = 0
        self.album_timeout_delay = 0.0
        self.album_delay = 0.0

    def get_artist_albums(self, artist_id: str) -> list[dict[str, Any]]:
        if self.fail_album_calls > 0:
            self.fail_album_calls -= 1
            if self.album_timeout_delay:
                time.sleep(self.album_timeout_delay)
        if self.album_delay:
            time.sleep(self.album_delay)
        return list(self.artist_albums.get(artist_id, []))

    def get_album_tracks(self, album_id: str) -> list[dict[str, Any]]:
        return list(self.album_tracks.get(album_id, []))


class RateLimitError(Exception):
    pass


class StubSoulseek:
    def __init__(self, *, delay: float = 0.0, rate_limit_failures: int = 0) -> None:
        self.delay = delay
        self.rate_limit_failures = rate_limit_failures
        self.search_results: list[dict[str, Any]] = []
        self.queries: list[str] = []
        self.active = 0
        self.max_active = 0

    async def search(self, query: str) -> list[dict[str, Any]]:
        self.queries.append(query)
        self.active += 1
        try:
            self.max_active = max(self.max_active, self.active)
            if self.rate_limit_failures > 0:
                self.rate_limit_failures -= 1
                raise RateLimitError("rate limited")
            if self.delay:
                await asyncio.sleep(self.delay)
            return list(self.search_results)
        finally:
            self.active -= 1


class StubSyncWorker:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    async def enqueue(self, job: dict[str, Any]) -> None:
        self.jobs.append(job)


class ThreadRecordingDAO(WatchlistDAO):
    def __init__(self) -> None:
        super().__init__()
        self.calls: defaultdict[str, list[str]] = defaultdict(list)

    def _record(self, name: str) -> None:
        self.calls[name].append(threading.current_thread().name)

    def load_batch(self, limit: int, *, cutoff: datetime | None = None) -> list[Any]:
        self._record("load_batch")
        return super().load_batch(limit, cutoff=cutoff)

    def mark_in_progress(self, artist_id: int) -> bool:
        self._record("mark_in_progress")
        return super().mark_in_progress(artist_id)

    def mark_success(self, artist_id: int, *, checked_at: datetime | None = None) -> None:
        self._record("mark_success")
        super().mark_success(artist_id, checked_at=checked_at)

    def mark_failed(self, artist_id: int, *, reason: str, retry_at: datetime | None = None) -> None:
        self._record("mark_failed")
        super().mark_failed(artist_id, reason=reason, retry_at=retry_at)

    def load_existing_track_ids(self, track_ids: Sequence[str]) -> set[str]:
        self._record("load_existing_track_ids")
        return super().load_existing_track_ids(track_ids)

    def create_download_record(
        self,
        *,
        username: str,
        filename: str,
        priority: int,
        spotify_track_id: str,
        spotify_album_id: str,
        payload: dict[str, Any],
    ) -> int | None:
        self._record("create_download_record")
        return super().create_download_record(
            username=username,
            filename=filename,
            priority=priority,
            spotify_track_id=spotify_track_id,
            spotify_album_id=spotify_album_id,
            payload=payload,
        )

    def mark_download_failed(self, download_id: int, reason: str) -> None:
        self._record("mark_download_failed")
        super().mark_download_failed(download_id, reason)


def _make_config(**overrides: Any) -> WatchlistWorkerConfig:
    return WatchlistWorkerConfig(
        max_concurrency=overrides.get("max_concurrency", 2),
        max_per_tick=overrides.get("max_per_tick", 5),
        spotify_timeout_ms=overrides.get("spotify_timeout_ms", 200),
        slskd_search_timeout_ms=overrides.get("slskd_search_timeout_ms", 500),
        tick_budget_ms=overrides.get("tick_budget_ms", 2_000),
        backoff_base_ms=overrides.get("backoff_base_ms", 50),
        retry_max=overrides.get("retry_max", 2),
        jitter_pct=overrides.get("jitter_pct", 0.0),
        shutdown_grace_ms=overrides.get("shutdown_grace_ms", 200),
        db_io_mode=overrides.get("db_io_mode", "thread"),
    )


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
async def test_watchlist_parallel_processing_respects_semaphore() -> None:
    for index in range(5):
        _insert_artist(
            f"artist-{index}",
            last_checked=datetime.utcnow() - timedelta(days=2),
        )

    spotify = StubSpotify()
    soulseek = StubSoulseek(delay=0.05)
    soulseek.search_results = [
        {
            "username": "watcher",
            "files": [{"filename": "Watcher - Track.flac", "priority": 0}],
        }
    ]
    for index in range(5):
        artist_id = f"artist-{index}"
        album_id = f"album-{index}"
        track_id = f"track-{index}"
        spotify.artist_albums[artist_id] = [
            {
                "id": album_id,
                "name": f"Release {index}",
                "artists": [{"name": f"Watcher {index}"}],
                "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
                "release_date_precision": "day",
            }
        ]
        spotify.album_tracks[album_id] = [
            {
                "id": track_id,
                "name": f"Track {index}",
                "artists": [{"name": f"Watcher {index}"}],
            }
        ]

    sync_worker = StubSyncWorker()
    config = _make_config(max_concurrency=2, retry_max=1)
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.1,
        dao=WatchlistDAO(),
    )

    outcomes = await worker.run_once()
    assert len(outcomes) == 5
    assert all(outcome.status == "ok" for outcome in outcomes)
    assert soulseek.max_active <= 2
    assert len(sync_worker.jobs) == 5


@pytest.mark.asyncio
async def test_watchlist_spotify_timeout_then_retry_success() -> None:
    artist_db_id = _insert_artist(
        "artist-timeout",
        last_checked=datetime.utcnow() - timedelta(days=1),
    )

    spotify = StubSpotify()
    spotify.fail_album_calls = 1
    spotify.album_timeout_delay = 0.2
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
            "name": "Wait",
            "artists": [{"name": "Watcher"}],
        }
    ]

    soulseek = StubSoulseek()
    soulseek.search_results = [
        {
            "username": "watcher",
            "files": [{"filename": "Watcher - Wait.flac", "priority": 0}],
        }
    ]
    sync_worker = StubSyncWorker()
    config = _make_config(spotify_timeout_ms=50, retry_max=3, backoff_base_ms=10)
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.05,
        dao=WatchlistDAO(),
    )

    before = datetime.utcnow()
    outcomes = await worker.run_once()
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.status == "ok"
    assert outcome.attempts == 2
    assert len(sync_worker.jobs) == 1
    assert len(soulseek.queries) == 1

    with session_scope() as session:
        refreshed = session.get(WatchlistArtist, artist_db_id)
        assert refreshed is not None
        assert refreshed.last_checked is not None
        assert refreshed.last_checked >= before


@pytest.mark.asyncio
async def test_watchlist_slskd_rate_limit_exhaustion_marks_failure() -> None:
    artist_db_id = _insert_artist(
        "artist-ratelimit",
        last_checked=datetime.utcnow() - timedelta(days=1),
    )

    spotify = StubSpotify()
    spotify.artist_albums["artist-ratelimit"] = [
        {
            "id": "album-ratelimit",
            "name": "Clogged",
            "artists": [{"name": "Watcher"}],
            "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "release_date_precision": "day",
        }
    ]
    spotify.album_tracks["album-ratelimit"] = [
        {
            "id": "track-ratelimit",
            "name": "Retry",
            "artists": [{"name": "Watcher"}],
        }
    ]

    soulseek = StubSoulseek(rate_limit_failures=3)
    soulseek.search_results = [
        {
            "username": "watcher",
            "files": [{"filename": "Watcher - Retry.flac", "priority": 0}],
        }
    ]
    sync_worker = StubSyncWorker()
    config = _make_config(retry_max=3, backoff_base_ms=15)
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.05,
        dao=WatchlistDAO(),
    )

    before = datetime.utcnow()
    outcomes = await worker.run_once()
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.status == "dependency_error"
    assert outcome.attempts == 3
    assert len(sync_worker.jobs) == 0
    assert len(soulseek.queries) == 3

    with session_scope() as session:
        refreshed = session.get(WatchlistArtist, artist_db_id)
        assert refreshed is not None
        assert refreshed.last_checked is not None
        assert refreshed.last_checked > before


@pytest.mark.asyncio
async def test_watchlist_db_ops_execute_in_thread_mode() -> None:
    _insert_artist("artist-thread", last_checked=datetime.utcnow() - timedelta(days=1))

    spotify = StubSpotify()
    spotify.artist_albums["artist-thread"] = [
        {
            "id": "album-thread",
            "name": "Threaded",
            "artists": [{"name": "Watcher"}],
            "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "release_date_precision": "day",
        }
    ]
    spotify.album_tracks["album-thread"] = [
        {
            "id": "track-thread",
            "name": "Worker",
            "artists": [{"name": "Watcher"}],
        }
    ]

    soulseek = StubSoulseek()
    soulseek.search_results = [
        {
            "username": "watcher",
            "files": [{"filename": "Watcher - Worker.flac", "priority": 0}],
        }
    ]
    sync_worker = StubSyncWorker()
    dao = ThreadRecordingDAO()
    config = _make_config(db_io_mode="thread", retry_max=1)
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.05,
        dao=dao,
    )

    await worker.run_once()

    main_thread = threading.current_thread().name
    recorded_threads = [thread_name for calls in dao.calls.values() for thread_name in calls]
    assert recorded_threads
    assert all(name != main_thread for name in recorded_threads)


@pytest.mark.asyncio
async def test_watchlist_idempotent_reprocessing_no_duplicates() -> None:
    artist_db_id = _insert_artist(
        "artist-idempotent",
        last_checked=datetime.utcnow() - timedelta(days=1),
    )

    spotify = StubSpotify()
    spotify.artist_albums["artist-idempotent"] = [
        {
            "id": "album-idempotent",
            "name": "Echo",
            "artists": [{"name": "Watcher"}],
            "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "release_date_precision": "day",
        }
    ]
    spotify.album_tracks["album-idempotent"] = [
        {
            "id": "track-idempotent",
            "name": "Loop",
            "artists": [{"name": "Watcher"}],
        }
    ]

    soulseek = StubSoulseek()
    soulseek.search_results = [
        {
            "username": "watcher",
            "files": [{"filename": "Watcher - Loop.flac", "priority": 0}],
        }
    ]
    sync_worker = StubSyncWorker()
    config = _make_config(retry_max=1)
    worker = WatchlistWorker(
        spotify_client=spotify,
        soulseek_client=soulseek,
        sync_worker=sync_worker,
        config=config,
        interval_seconds=0.05,
        dao=WatchlistDAO(),
    )

    first_outcomes = await worker.run_once()
    assert first_outcomes[0].status == "ok"
    assert len(sync_worker.jobs) == 1

    with session_scope() as session:
        downloads = session.execute(select(Download)).scalars().all()
        assert len(downloads) == 1
        refreshed = session.get(WatchlistArtist, artist_db_id)
        assert refreshed is not None
        refreshed.last_checked = datetime.utcnow() - timedelta(days=1)
        session.add(refreshed)

    second_outcomes = await worker.run_once()
    assert second_outcomes[0].status == "noop"
    assert second_outcomes[0].queued == 0
    assert len(sync_worker.jobs) == 1
    assert len(soulseek.queries) == 1

    with session_scope() as session:
        downloads = session.execute(select(Download)).scalars().all()
        assert len(downloads) == 1
