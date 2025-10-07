from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.integrations.artist_gateway import ArtistGatewayResponse, ArtistGatewayResult
from app.integrations.contracts import ProviderArtist, ProviderRelease
from app.integrations.provider_gateway import ProviderGatewayTimeoutError
from app.models import ArtistRecord, ArtistReleaseRecord, ArtistWatchlistEntry, QueueJobStatus
from app.orchestrator.artist_sync import (
    ArtistSyncHandlerDeps,
    enqueue_artist_sync,
    handle_artist_sync,
)
from app.services.artist_dao import ArtistDao, ArtistUpsertDTO
from app.services.cache import build_path_param_hash
from app.workers import persistence
from app.workers.persistence import QueueJobDTO


class _StubGateway:
    def __init__(
        self, response: ArtistGatewayResponse | None = None, error: Exception | None = None
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[Mapping[str, Any]] = []

    async def fetch_artist(
        self,
        artist_id: str,
        *,
        providers: Sequence[str],
        limit: int,
    ) -> ArtistGatewayResponse:
        self.calls.append({"artist_id": artist_id, "providers": tuple(providers), "limit": limit})
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


class _StubCache:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any]]] = []
        self.write_through = True

    async def invalidate_prefix(self, prefix: str, **kwargs: Any) -> int:
        self.calls.append((prefix, dict(kwargs)))
        return 1


@pytest.fixture(autouse=True)
def _db() -> None:
    reset_engine_for_tests()
    init_db()


@pytest.mark.asyncio
async def test_artist_sync_upserts_artist_and_releases() -> None:
    response = ArtistGatewayResponse(
        artist_id="artist-1",
        results=(
            ArtistGatewayResult(
                provider="spotify",
                artist=ProviderArtist(
                    source="spotify",
                    source_id="artist-1",
                    name="Gateway Artist",
                    genres=("rock",),
                    images=("https://img/artist-1",),
                    popularity=55,
                ),
                releases=(
                    ProviderRelease(
                        source="spotify",
                        source_id="release-1",
                        artist_source_id="artist-1",
                        title="First",
                        type="album",
                        release_date="2024-01-01",
                    ),
                    ProviderRelease(
                        source="spotify",
                        source_id="release-2",
                        artist_source_id="artist-1",
                        title="Second",
                        type="single",
                        release_date="2024-02-01",
                    ),
                ),
            ),
        ),
    )

    gateway = _StubGateway(response)
    dao = ArtistDao(now_factory=lambda: datetime(2024, 5, 1, 10, 0, 0))
    deps = ArtistSyncHandlerDeps(
        gateway=gateway,
        dao=dao,
        providers=("spotify",),
        release_limit=10,
        cooldown_minutes=0,
    )

    job = QueueJobDTO(
        id=1,
        type="artist_sync",
        payload={"artist_key": "spotify:artist-1"},
        priority=0,
        attempts=0,
        available_at=datetime.utcnow(),
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key="artist-sync-1",
    )

    result = await handle_artist_sync(job, deps)

    assert result["status"] == "ok"
    assert result["artist_key"] == "spotify:artist-1"
    assert result["release_count"] == 2
    assert result["watchlist_updated"] is False

    with session_scope() as session:
        artist_record = (
            session.query(ArtistRecord).filter(ArtistRecord.artist_key == "spotify:artist-1").one()
        )
        assert artist_record.name == "Gateway Artist"
        releases = (
            session.query(ArtistReleaseRecord)
            .filter(ArtistReleaseRecord.artist_key == artist_record.artist_key)
            .all()
        )
        assert len(releases) == 2
        titles = {release.title for release in releases}
        assert titles == {"First", "Second"}


@pytest.mark.asyncio
async def test_artist_sync_is_idempotent_by_key() -> None:
    first = await enqueue_artist_sync("spotify:artist-1")
    second = await enqueue_artist_sync("spotify:artist-1")

    assert first.id == second.id
    ready = persistence.fetch_ready("artist_sync")
    assert len(ready) == 1
    assert ready[0].payload["artist_key"] == "spotify:artist-1"


@pytest.mark.asyncio
async def test_artist_sync_sets_cooldown_and_last_synced() -> None:
    dao = ArtistDao(now_factory=lambda: datetime(2024, 5, 1, 10, 0, 0))
    dao.upsert_artist(
        ArtistUpsertDTO(
            artist_key="spotify:artist-1",
            source="spotify",
            source_id="artist-1",
            name="Existing Artist",
        )
    )
    dao.upsert_watchlist_entry("spotify:artist-1", priority=5)

    response = ArtistGatewayResponse(artist_id="artist-1", results=())
    deps = ArtistSyncHandlerDeps(
        gateway=_StubGateway(response),
        dao=dao,
        providers=("spotify",),
        release_limit=5,
        now_factory=lambda: datetime(2024, 5, 2, 12, 0, 0),
        cooldown_minutes=30,
        priority_decay=2,
    )

    job = QueueJobDTO(
        id=2,
        type="artist_sync",
        payload={"artist_key": "spotify:artist-1"},
        priority=0,
        attempts=0,
        available_at=datetime.utcnow(),
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key="artist-sync-2",
    )

    result = await handle_artist_sync(job, deps)
    assert result["status"] == "noop"
    assert result["watchlist_updated"] is True

    expected_synced_at = datetime(2024, 5, 2, 12, 0, 0)
    expected_cooldown = expected_synced_at + timedelta(minutes=30)

    with session_scope() as session:
        entry = session.get(ArtistWatchlistEntry, "spotify:artist-1")
        assert entry is not None
        assert entry.last_synced_at == expected_synced_at
        assert entry.cooldown_until == expected_cooldown
        assert int(entry.priority) == 3


@pytest.mark.asyncio
async def test_artist_sync_evicts_artist_cache() -> None:
    response = ArtistGatewayResponse(artist_id="artist-1", results=())
    cache = _StubCache()
    deps = ArtistSyncHandlerDeps(
        gateway=_StubGateway(response),
        dao=ArtistDao(),
        providers=("spotify",),
        release_limit=5,
        response_cache=cache,
        api_base_path="/api/v1",
        cooldown_minutes=0,
    )

    job = QueueJobDTO(
        id=3,
        type="artist_sync",
        payload={"artist_key": "spotify:artist-1"},
        priority=0,
        attempts=0,
        available_at=datetime.utcnow(),
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key="artist-sync-3",
    )

    await handle_artist_sync(job, deps)

    assert cache.calls
    path_hash = build_path_param_hash({"artist_key": "spotify:artist-1"})
    prefixes = [call[0] for call in cache.calls]
    assert any(
        prefix.startswith(f"GET:/artists/{{artist_key}}:{path_hash}:") for prefix in prefixes
    )
    assert any(
        prefix.startswith(f"GET:/api/v1/artists/{{artist_key}}:{path_hash}:") for prefix in prefixes
    )


@pytest.mark.asyncio
async def test_artist_sync_dependency_error_retries_then_dlq() -> None:
    error = ProviderGatewayTimeoutError("spotify", timeout_ms=1000)
    deps = ArtistSyncHandlerDeps(
        gateway=_StubGateway(error=error),
        dao=ArtistDao(),
        providers=("spotify",),
        release_limit=5,
        cooldown_minutes=0,
    )

    job = QueueJobDTO(
        id=4,
        type="artist_sync",
        payload={"artist_key": "spotify:artist-1"},
        priority=0,
        attempts=1,
        available_at=datetime.utcnow(),
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key="artist-sync-4",
    )

    with pytest.raises(ProviderGatewayTimeoutError):
        await handle_artist_sync(job, deps)
