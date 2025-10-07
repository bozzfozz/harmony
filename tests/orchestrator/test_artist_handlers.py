from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Mapping

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import WatchlistWorkerConfig
from app.orchestrator.handlers import (
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
    ) -> None:
        self.marked_success.append(artist_id)

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
async def test_artist_delta_queues_downloads_with_idempotency_and_retry() -> None:
    artist = ArtistWorkflowArtistRow(
        id=1,
        spotify_artist_id="artist-1",
        name="Artist",
        last_checked=None,
        retry_block_until=None,
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

    job = _queue_job(job_type="artist_delta", payload={"artist_id": artist.id})
    result = await handle_artist_delta(job, deps)

    assert result["status"] == "ok"
    assert result["queued"] == 1
    assert len(submitter.calls) == 2
    assert submitter.calls[0]["idempotency_key"].startswith("watchlist-download:")
    assert submitter.calls[0]["priority"] == submitter.calls[1]["priority"]
    assert dao.failures == []
    assert dao.marked_success == [artist.id]
    assert cache.hints and cache.hints[0][0] == artist.spotify_artist_id
