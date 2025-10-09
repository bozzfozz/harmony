from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Iterator, Mapping

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import WatchlistWorkerConfig, settings
from app.dependencies import get_app_config
from app.orchestrator.handlers import (
    ARTIST_SCAN_JOB_TYPE,
    ArtistDeltaHandlerDeps,
    ArtistRefreshHandlerDeps,
    handle_artist_delta,
    handle_artist_refresh,
)
from app.services.artist_workflow_dao import ArtistWorkflowArtistRow
from app.workers.persistence import QueueJobDTO, QueueJobStatus


class _StubCacheService:
    def __init__(self) -> None:
        self.evicted: list[str] = []
        self.hints: list[tuple[str, Any]] = []

    async def update_hint(self, *, artist_id: str, hint: Any) -> None:
        self.hints.append((artist_id, hint))

    async def evict_artist(self, *, artist_id: str) -> None:
        self.evicted.append(artist_id)


@pytest.fixture(autouse=True)
def _enable_artist_cache_flag() -> Iterator[None]:
    config = get_app_config()
    previous = config.features.enable_artist_cache_invalidation
    config.features.enable_artist_cache_invalidation = True
    try:
        yield
    finally:
        config.features.enable_artist_cache_invalidation = previous


def _watchlist_config() -> WatchlistWorkerConfig:
    return WatchlistWorkerConfig(
        max_concurrency=2,
        max_per_tick=5,
        spotify_timeout_ms=200,
        slskd_search_timeout_ms=200,
        tick_budget_ms=1_000,
        backoff_base_ms=100,
        retry_max=3,
        jitter_pct=0.0,
        shutdown_grace_ms=200,
        db_io_mode="thread",
        retry_budget_per_artist=3,
        cooldown_minutes=15,
    )


def _queue_job(
    *,
    job_type: str,
    payload: Mapping[str, Any],
    attempts: int = 0,
) -> QueueJobDTO:
    now = datetime.utcnow()
    return QueueJobDTO(
        id=1,
        type=job_type,
        payload=dict(payload),
        priority=0,
        attempts=attempts,
        available_at=now,
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key=None,
    )


class _StubRefreshDAO:
    def __init__(self, artist: ArtistWorkflowArtistRow | None) -> None:
        self._artist = artist

    def get_artist(self, artist_id: int) -> ArtistWorkflowArtistRow | None:
        return self._artist


class _StubDeltaDAO:
    def __init__(self, artist: ArtistWorkflowArtistRow) -> None:
        self._artist = artist
        self.created: list[dict[str, Any]] = []
        self.failures: list[tuple[int, str]] = []
        self.marked_success: list[int] = []
        self.marked_failed: list[dict[str, Any]] = []
        self.last_hash: str | None = artist.last_hash

    def get_artist(self, artist_id: int) -> ArtistWorkflowArtistRow | None:
        return self._artist if self._artist.id == artist_id else None

    def load_known_releases(self, artist_id: int) -> dict[str, object]:
        return {}

    def load_existing_track_ids(self, track_ids: list[str]) -> set[str]:
        return set()

    def create_download_record(
        self,
        *,
        username: str,
        filename: str,
        priority: int,
        spotify_track_id: str,
        spotify_album_id: str,
        payload: Mapping[str, Any],
        artist_id: int | None = None,
        known_release=None,
    ) -> int:
        download_id = len(self.created) + 1
        self.created.append(
            {
                "username": username,
                "filename": filename,
                "priority": priority,
                "spotify_track_id": spotify_track_id,
                "spotify_album_id": spotify_album_id,
                "payload": dict(payload),
                "artist_id": artist_id,
                "known_release": known_release,
            }
        )
        return download_id

    def mark_download_failed(self, download_id: int, reason: str) -> None:
        self.failures.append((download_id, reason))

    def mark_success(
        self,
        artist_id: int,
        *,
        checked_at: datetime | None = None,
        known_releases=None,
        content_hash: str | None = None,
    ) -> None:
        self.marked_success.append(artist_id)
        self.last_hash = content_hash

    def mark_failed(
        self,
        artist_id: int,
        *,
        reason: str,
        retry_at: datetime | None = None,
        retry_block_until: datetime | None | object = None,
    ) -> None:
        self.marked_failed.append(
            {
                "artist_id": artist_id,
                "reason": reason,
                "retry_at": retry_at,
                "retry_block_until": retry_block_until,
            }
        )


class _StubSpotifyClient:
    def __init__(self) -> None:
        self.albums: list[dict[str, Any]] = []
        self.tracks: dict[str, list[dict[str, Any]]] = {}

    def get_artist_albums(self, artist_id: str) -> list[dict[str, Any]]:
        return list(self.albums)

    def get_album_tracks(self, album_id: str) -> list[dict[str, Any]]:
        return list(self.tracks.get(album_id, []))


class _StubSoulseekClient:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    async def search(self, query: str) -> list[dict[str, Any]]:
        await asyncio.sleep(0)
        return list(self.results)


class _RecordingSubmitter:
    def __init__(self, fail_once: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail_once = fail_once

    async def __call__(
        self,
        payload: Mapping[str, Any],
        *,
        priority: int,
        idempotency_key: str,
    ) -> Mapping[str, Any] | None:
        self.calls.append(
            {
                "payload": dict(payload),
                "priority": priority,
                "idempotency_key": idempotency_key,
            }
        )
        if self._fail_once:
            self._fail_once = False
            raise IntegrityError("duplicate", None, None)
        return {"status": "queued"}


@pytest.mark.asyncio
async def test_artist_refresh_retries_on_integrity_error() -> None:
    artist = ArtistWorkflowArtistRow(
        id=1,
        spotify_artist_id="artist-1",
        name="Artist",
        last_checked=None,
        retry_block_until=None,
        last_hash=None,
    )
    cache = _StubCacheService()
    submitter = _RecordingSubmitter(fail_once=True)
    deps = ArtistRefreshHandlerDeps(
        config=_watchlist_config(),
        dao=_StubRefreshDAO(artist),
        submit_delta_job=submitter,
        cache_service=cache,
    )

    job = _queue_job(job_type="artist_refresh", payload={"artist_id": artist.id})
    result = await handle_artist_refresh(job, deps)

    assert result["status"] == "enqueued"
    assert len(submitter.calls) == 2
    for call in submitter.calls:
        assert call["idempotency_key"].startswith("artist-delta:1:")
        assert call["priority"] == deps.delta_priority
    assert cache.evicted == [artist.spotify_artist_id]


@pytest.mark.asyncio
async def test_artist_refresh_uses_priority_override() -> None:
    artist = ArtistWorkflowArtistRow(
        id=1,
        spotify_artist_id="artist-1",
        name="Artist",
        last_checked=None,
        retry_block_until=None,
        last_hash=None,
    )
    cache = _StubCacheService()
    submitter = _RecordingSubmitter()
    previous_priorities = dict(settings.orchestrator.priority_map)
    settings.orchestrator.priority_map[ARTIST_SCAN_JOB_TYPE] = 77
    settings.orchestrator.priority_map["artist_delta"] = 77
    try:
        deps = ArtistRefreshHandlerDeps(
            config=_watchlist_config(),
            dao=_StubRefreshDAO(artist),
            submit_delta_job=submitter,
            cache_service=cache,
        )

        job = _queue_job(job_type="artist_refresh", payload={"artist_id": artist.id})
        result = await handle_artist_refresh(job, deps)
    finally:
        settings.orchestrator.priority_map.update(previous_priorities)

    assert result["status"] == "enqueued"
    assert submitter.calls
    assert submitter.calls[0]["priority"] == 77


@pytest.mark.asyncio
async def test_artist_delta_queues_downloads_with_idempotency_and_retry() -> None:
    artist = ArtistWorkflowArtistRow(
        id=1,
        spotify_artist_id="artist-1",
        name="Artist",
        last_checked=None,
        retry_block_until=None,
        last_hash=None,
    )
    dao = _StubDeltaDAO(artist)
    spotify = _StubSpotifyClient()
    album_id = "album-1"
    track_id = "track-1"
    spotify.albums = [
        {
            "id": album_id,
            "name": "Album",
            "release_date": "2023-01-01",
            "release_date_precision": "day",
        }
    ]
    spotify.tracks[album_id] = [
        {
            "id": track_id,
            "name": "Track",
            "artists": [{"name": "Artist"}],
            "duration_ms": 123_000,
        }
    ]
    soulseek = _StubSoulseekClient()
    soulseek.results = [
        {
            "username": "user",
            "files": [
                {
                    "filename": "Artist - Track.flac",
                    "priority": 2,
                }
            ],
        }
    ]
    cache = _StubCacheService()
    submitter = _RecordingSubmitter(fail_once=True)
    deps = ArtistDeltaHandlerDeps(
        spotify_client=spotify,
        soulseek_client=soulseek,
        config=_watchlist_config(),
        dao=dao,
        submit_sync_job=submitter,
        cache_service=cache,
    )

    job = _queue_job(job_type=ARTIST_SCAN_JOB_TYPE, payload={"artist_id": artist.id})
    result = await handle_artist_delta(job, deps)

    assert result["status"] == "ok"
    assert result["queued"] == 1
    assert len(submitter.calls) == 2
    assert submitter.calls[0]["idempotency_key"].startswith("watchlist-download:")
    assert submitter.calls[0]["priority"] == submitter.calls[1]["priority"]
    assert dao.failures == []
    assert dao.marked_success == [artist.id]
    assert cache.hints and cache.hints[0][0] == artist.spotify_artist_id
    hint = cache.hints[-1][1]
    assert hint is not None
    assert hint.etag.startswith('"artist-delta:')
    assert cache.evicted == [artist.spotify_artist_id]


@pytest.mark.asyncio
async def test_artist_delta_updates_cache_hint_on_no_changes() -> None:
    artist = ArtistWorkflowArtistRow(
        id=1,
        spotify_artist_id="artist-1",
        name="Artist",
        last_checked=datetime.utcnow(),
        retry_block_until=None,
        last_hash=None,
    )
    dao = _StubDeltaDAO(artist)
    spotify = _StubSpotifyClient()
    soulseek = _StubSoulseekClient()
    cache = _StubCacheService()
    deps = ArtistDeltaHandlerDeps(
        spotify_client=spotify,
        soulseek_client=soulseek,
        config=_watchlist_config(),
        dao=dao,
        cache_service=cache,
    )

    job = _queue_job(job_type=ARTIST_SCAN_JOB_TYPE, payload={"artist_id": artist.id})
    result = await handle_artist_delta(job, deps)

    assert result["status"] == "noop"
    assert cache.hints == [(artist.spotify_artist_id, None)]
    assert cache.evicted == [artist.spotify_artist_id]


@pytest.mark.asyncio
async def test_artist_delta_skips_when_content_hash_matches() -> None:
    base_artist = ArtistWorkflowArtistRow(
        id=1,
        spotify_artist_id="artist-1",
        name="Artist",
        last_checked=None,
        retry_block_until=None,
        last_hash=None,
    )
    dao = _StubDeltaDAO(base_artist)
    spotify = _StubSpotifyClient()
    album_id = "album-unchanged"
    track_id = "track-unchanged"
    spotify.albums = [
        {
            "id": album_id,
            "name": "Album",
            "release_date": "2024-01-01",
            "release_date_precision": "day",
        }
    ]
    spotify.tracks[album_id] = [
        {
            "id": track_id,
            "name": "Track",
            "artists": [{"name": "Artist"}],
            "duration_ms": 120_000,
        }
    ]
    soulseek = _StubSoulseekClient()
    soulseek.results = [
        {
            "username": "user",
            "files": [
                {
                    "filename": "Artist - Track.flac",
                    "priority": 1,
                }
            ],
        }
    ]
    cache = _StubCacheService()
    submitter = _RecordingSubmitter()
    deps = ArtistDeltaHandlerDeps(
        spotify_client=spotify,
        soulseek_client=soulseek,
        config=_watchlist_config(),
        dao=dao,
        submit_sync_job=submitter,
        cache_service=cache,
    )
    job = _queue_job(job_type=ARTIST_SCAN_JOB_TYPE, payload={"artist_id": base_artist.id})
    await handle_artist_delta(job, deps)
    previous_hash = dao.last_hash
    assert previous_hash

    unchanged_artist = ArtistWorkflowArtistRow(
        id=1,
        spotify_artist_id="artist-1",
        name="Artist",
        last_checked=None,
        retry_block_until=None,
        last_hash=previous_hash,
    )
    unchanged_dao = _StubDeltaDAO(unchanged_artist)
    unchanged_cache = _StubCacheService()
    unchanged_submitter = _RecordingSubmitter()
    unchanged_deps = ArtistDeltaHandlerDeps(
        spotify_client=spotify,
        soulseek_client=soulseek,
        config=_watchlist_config(),
        dao=unchanged_dao,
        submit_sync_job=unchanged_submitter,
        cache_service=unchanged_cache,
    )
    second_job = _queue_job(
        job_type=ARTIST_SCAN_JOB_TYPE, payload={"artist_id": unchanged_artist.id}
    )
    result = await handle_artist_delta(second_job, unchanged_deps)

    assert result["status"] == "noop"
    assert result["queued"] == 0
    assert result.get("reason") == "unchanged"
    assert unchanged_submitter.calls == []
    assert unchanged_cache.hints == [(unchanged_artist.spotify_artist_id, None)]
    assert unchanged_cache.evicted == []
    assert unchanged_dao.last_hash == previous_hash
