from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

import pytest
from sqlalchemy import select

from app.db import init_db, reset_engine_for_tests, session_scope
from app.integrations.artist_gateway import (ArtistGatewayResponse,
                                             ArtistGatewayResult)
from app.integrations.contracts import ProviderArtist, ProviderRelease
from app.models import ArtistRecord, ArtistReleaseRecord, QueueJobStatus
from app.orchestrator.artist_sync import (ArtistSyncHandlerDeps,
                                          enqueue_artist_sync,
                                          handle_artist_sync)
from app.services.artist_dao import ArtistDao
from app.workers import persistence
from app.workers.persistence import QueueJobDTO


class _StubGateway:
    def __init__(self, response: ArtistGatewayResponse) -> None:
        self._response = response
        self.calls: list[Mapping[str, object]] = []

    async def fetch_artist(
        self,
        artist_id: str,
        *,
        providers: Sequence[str],
        limit: int,
    ) -> ArtistGatewayResponse:
        self.calls.append({"artist_id": artist_id, "providers": tuple(providers), "limit": limit})
        return self._response


@pytest.mark.asyncio
async def test_enqueue_artist_sync_is_redelivery_safe() -> None:
    reset_engine_for_tests()
    init_db()

    first = await enqueue_artist_sync("spotify:artist-1")
    second = await enqueue_artist_sync("spotify:artist-1")

    assert first.id == second.id
    ready = persistence.fetch_ready("artist_sync")
    assert len(ready) == 1
    assert ready[0].payload["artist_key"] == "spotify:artist-1"


@pytest.mark.asyncio
async def test_orchestrator_handler_persists_artist_and_releases() -> None:
    reset_engine_for_tests()
    init_db()

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
                        source_id="release-1",
                        artist_source_id="artist-1",
                        title="First (alt)",
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
    deps = ArtistSyncHandlerDeps(gateway=gateway, dao=dao, providers=("spotify",), release_limit=10)

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
    assert result["artist_version"]
    assert result["added_releases"] == 2
    assert result["updated_releases"] == 0
    assert result["inactivated_releases"] == 0
    assert result["alias_added"] == 0
    assert result["alias_removed"] == 0

    with session_scope() as session:
        artist_record = (
            session.execute(
                select(ArtistRecord).where(ArtistRecord.artist_key == "spotify:artist-1")
            )
            .scalars()
            .one()
        )
        assert artist_record.name == "Gateway Artist"
        releases = (
            session.execute(
                select(ArtistReleaseRecord).where(
                    ArtistReleaseRecord.artist_key == artist_record.artist_key
                )
            )
            .scalars()
            .all()
        )
        assert len(releases) == 2
        titles = {release.title for release in releases}
        assert titles == {"First (alt)", "Second"}


@pytest.mark.asyncio
async def test_idempotent_second_run_noops() -> None:
    reset_engine_for_tests()
    init_db()

    response = ArtistGatewayResponse(
        artist_id="artist-2",
        results=(
            ArtistGatewayResult(
                provider="spotify",
                artist=ProviderArtist(
                    source="spotify",
                    source_id="artist-2",
                    name="Repeat Artist",
                ),
                releases=(
                    ProviderRelease(
                        source="spotify",
                        source_id="release-10",
                        artist_source_id="artist-2",
                        title="Only Release",
                        type="album",
                        release_date="2024-05-01",
                    ),
                ),
            ),
        ),
    )

    gateway = _StubGateway(response)
    dao = ArtistDao(now_factory=lambda: datetime(2024, 5, 2, 9, 0, 0))
    deps = ArtistSyncHandlerDeps(gateway=gateway, dao=dao, providers=("spotify",), release_limit=5)

    job = QueueJobDTO(
        id=2,
        type="artist_sync",
        payload={"artist_key": "spotify:artist-2"},
        priority=0,
        attempts=0,
        available_at=datetime.utcnow(),
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key="artist-sync-2",
    )

    first = await handle_artist_sync(job, deps)
    assert first["added_releases"] == 1

    second = await handle_artist_sync(job, deps)
    assert second["status"] == "ok"
    assert second["added_releases"] == 0
    assert second["updated_releases"] == 0
    assert second["inactivated_releases"] == 0
    assert second["release_count"] == 0


__all__ = [
    "test_enqueue_artist_sync_is_redelivery_safe",
    "test_orchestrator_handler_persists_artist_and_releases",
    "test_idempotent_second_run_noops",
]
