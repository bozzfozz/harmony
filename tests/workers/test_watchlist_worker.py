from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.config import WatchlistWorkerConfig
from app.db import session_scope
from app.models import Download, QueueJob, QueueJobStatus, WatchlistArtist
from app.orchestrator.dispatcher import Dispatcher
from app.orchestrator.handlers import WatchlistHandlerDeps, build_watchlist_handler
from app.services.artist_workflow_dao import ArtistWorkflowDAO
from app.workers import persistence


class StubSpotify:
    def __init__(self) -> None:
        self.artist_albums: dict[str, list[dict[str, Any]]] = {}
        self.album_tracks: dict[str, list[dict[str, Any]]] = {}
        self.fail_albums = False

    def get_artist_albums(self, artist_id: str) -> list[dict[str, Any]]:
        if self.fail_albums:
            raise TimeoutError("spotify timeout")
        return list(self.artist_albums.get(artist_id, []))

    def get_album_tracks(self, album_id: str) -> list[dict[str, Any]]:
        return list(self.album_tracks.get(album_id, []))


class StubSoulseek:
    def __init__(self) -> None:
        self.search_results: list[dict[str, Any]] = []

    async def search(self, query: str) -> list[dict[str, Any]]:
        await asyncio.sleep(0)
        return list(self.search_results)


class StubSyncSubmitter:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    async def __call__(
        self,
        payload: dict[str, Any],
        *,
        priority: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        copy = dict(payload)
        if priority is not None:
            copy.setdefault("priority", priority)
        if idempotency_key is not None:
            copy.setdefault("idempotency_key", idempotency_key)
        self.jobs.append(copy)
        return copy


class DummyScheduler:
    poll_interval = 0.01

    def lease_ready_jobs(self) -> list[persistence.QueueJobDTO]:
        return []


def _make_config(**overrides: Any) -> WatchlistWorkerConfig:
    return WatchlistWorkerConfig(
        max_concurrency=overrides.get("max_concurrency", 2),
        max_per_tick=overrides.get("max_per_tick", 5),
        spotify_timeout_ms=overrides.get("spotify_timeout_ms", 200),
        slskd_search_timeout_ms=overrides.get("slskd_search_timeout_ms", 200),
        tick_budget_ms=overrides.get("tick_budget_ms", 1_000),
        backoff_base_ms=overrides.get("backoff_base_ms", 100),
        retry_max=overrides.get("retry_max", 3),
        jitter_pct=overrides.get("jitter_pct", 0.0),
        shutdown_grace_ms=overrides.get("shutdown_grace_ms", 200),
        db_io_mode=overrides.get("db_io_mode", "thread"),
        retry_budget_per_artist=overrides.get("retry_budget_per_artist", 3),
        cooldown_minutes=overrides.get("cooldown_minutes", 15),
    )


def _insert_artist(
    spotify_artist_id: str,
    *,
    last_checked: datetime | None = None,
    retry_block_until: datetime | None = None,
) -> int:
    with session_scope() as session:
        artist = WatchlistArtist(
            spotify_artist_id=spotify_artist_id,
            name="Watcher",
            last_checked=last_checked,
            retry_block_until=retry_block_until,
        )
        session.add(artist)
        session.flush()
        return int(artist.id)


def _make_dispatcher(handler) -> Dispatcher:
    return Dispatcher(
        DummyScheduler(),
        {"watchlist": handler},
        global_concurrency=1,
        pool_concurrency={"watchlist": 1},
    )


@pytest.mark.asyncio
async def test_watchlist_handler_success_enqueues_sync_job() -> None:
    artist_id = _insert_artist("artist-1")

    spotify = StubSpotify()
    soulseek = StubSoulseek()
    submitter = StubSyncSubmitter()
    config = _make_config()

    album_id = "album-1"
    track_id = "track-1"
    spotify.artist_albums["artist-1"] = [
        {
            "id": album_id,
            "name": "Album",
            "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
        }
    ]
    spotify.album_tracks[album_id] = [
        {
            "id": track_id,
            "name": "Track",
            "artists": [{"name": "Watcher"}],
        }
    ]
    soulseek.search_results = [
        {
            "username": "watcher",
            "files": [{"filename": "Watcher - Track.flac", "priority": 0}],
        }
    ]

    deps = WatchlistHandlerDeps(
        spotify_client=spotify,
        soulseek_client=soulseek,
        config=config,
        dao=ArtistWorkflowDAO(),
        submit_sync_job=submitter,
    )
    handler = build_watchlist_handler(deps)
    dispatcher = _make_dispatcher(handler)

    job = persistence.enqueue("watchlist", {"artist_id": artist_id})
    leased = persistence.lease(job.id, job_type="watchlist", lease_seconds=30)
    assert leased is not None

    await dispatcher._execute_job(leased, handler)

    with session_scope() as session:
        record = session.get(QueueJob, job.id)
        assert record is not None
        assert record.status == QueueJobStatus.COMPLETED.value
        artist = session.get(WatchlistArtist, artist_id)
        assert artist is not None and artist.last_checked is not None
        downloads = session.execute(select(Download)).scalars().all()
        assert len(downloads) == 1
        assert downloads[0].spotify_track_id == track_id

    assert len(submitter.jobs) == 1
    job_payload = submitter.jobs[0]
    assert job_payload["files"][0]["download_id"] > 0


@pytest.mark.asyncio
async def test_watchlist_handler_retryable_failure_reschedules() -> None:
    artist_id = _insert_artist("artist-2")

    spotify = StubSpotify()
    spotify.fail_albums = True
    soulseek = StubSoulseek()
    submitter = StubSyncSubmitter()
    config = _make_config(backoff_base_ms=100)

    deps = WatchlistHandlerDeps(
        spotify_client=spotify,
        soulseek_client=soulseek,
        config=config,
        dao=ArtistWorkflowDAO(),
        submit_sync_job=submitter,
    )
    handler = build_watchlist_handler(deps)
    dispatcher = _make_dispatcher(handler)

    job = persistence.enqueue("watchlist", {"artist_id": artist_id})
    leased = persistence.lease(job.id, job_type="watchlist", lease_seconds=30)
    assert leased is not None

    await dispatcher._execute_job(leased, handler)

    with session_scope() as session:
        record = session.get(QueueJob, job.id)
        assert record is not None
        assert record.status == QueueJobStatus.PENDING.value
        assert record.last_error == "timeout"
        artist = session.get(WatchlistArtist, artist_id)
        assert artist is not None and artist.last_checked is not None
        assert artist.last_checked > datetime.utcnow()


class FailingDAO(ArtistWorkflowDAO):
    def create_download_record(self, *args, **kwargs):  # type: ignore[override]
        raise RuntimeError("persist failure")


def _force_ready(job_id: int) -> None:
    with session_scope() as session:
        record = session.get(QueueJob, job_id)
        assert record is not None
        record.available_at = datetime.utcnow() - timedelta(seconds=1)
        record.status = QueueJobStatus.PENDING.value
        session.add(record)


@pytest.mark.asyncio
async def test_watchlist_handler_moves_to_dlq_after_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXTERNAL_RETRY_MAX", "2")
    artist_id = _insert_artist("artist-3")

    spotify = StubSpotify()
    soulseek = StubSoulseek()
    submitter = StubSyncSubmitter()
    config = _make_config()

    album_id = "album-error"
    track_id = "track-error"
    spotify.artist_albums["artist-3"] = [
        {
            "id": album_id,
            "name": "Problem",
            "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
        }
    ]
    spotify.album_tracks[album_id] = [
        {
            "id": track_id,
            "name": "Problem",
            "artists": [{"name": "Watcher"}],
        }
    ]
    soulseek.search_results = [
        {
            "username": "watcher",
            "files": [{"filename": "Watcher - Problem.flac", "priority": 0}],
        }
    ]

    deps = WatchlistHandlerDeps(
        spotify_client=spotify,
        soulseek_client=soulseek,
        config=config,
        dao=FailingDAO(),
        submit_sync_job=submitter,
    )
    handler = build_watchlist_handler(deps)
    dispatcher = _make_dispatcher(handler)

    job = persistence.enqueue("watchlist", {"artist_id": artist_id})

    for _ in range(5):
        leased = persistence.lease(job.id, job_type="watchlist", lease_seconds=30)
        assert leased is not None
        await dispatcher._execute_job(leased, handler)
        with session_scope() as session:
            record = session.get(QueueJob, job.id)
            assert record is not None
            if record.status == QueueJobStatus.CANCELLED.value:
                break
        _force_ready(job.id)
    else:
        pytest.fail("watchlist job did not reach dead letter queue")

    with session_scope() as session:
        record = session.get(QueueJob, job.id)
        assert record is not None
        assert record.status == QueueJobStatus.CANCELLED.value
        assert record.last_error is not None
