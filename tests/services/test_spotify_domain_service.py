from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.config import load_config
from app.services.spotify_domain_service import PlaylistItemsResult, SpotifyDomainService


def _make_service(**overrides: Any) -> SpotifyDomainService:
    config = overrides.get("config", load_config())
    spotify_client = overrides.get("spotify_client", MagicMock())
    soulseek_client = overrides.get("soulseek_client", MagicMock())
    app_state = overrides.get("app_state", SimpleNamespace())
    return SpotifyDomainService(
        config=config,
        spotify_client=spotify_client,
        soulseek_client=soulseek_client,
        app_state=app_state,
        free_ingest_factory=overrides.get("free_ingest_factory"),
        backfill_service_factory=overrides.get("backfill_service_factory"),
        backfill_worker_factory=overrides.get("backfill_worker_factory"),
    )


def test_get_playlist_items_uses_fallback_total() -> None:
    spotify_client = MagicMock()
    spotify_client.get_playlist_items.return_value = {"items": [{"id": 1}, {"id": 2}]}
    service = _make_service(spotify_client=spotify_client)

    result = service.get_playlist_items("playlist", limit=10)

    assert isinstance(result, PlaylistItemsResult)
    assert result.total == 2
    assert list(result.items) == [{"id": 1}, {"id": 2}]


def test_get_artist_discography_merges_tracks() -> None:
    spotify_client = MagicMock()
    spotify_client.get_artist_discography.return_value = {
        "albums": [
            {
                "album": {"id": "a1"},
                "tracks": {"items": [{"name": "Track"}, "invalid", {"name": "Other"}]},
            },
            {
                "name": "Fallback",
                "tracks": [{"name": "Solo"}, None],
            },
        ]
    }
    service = _make_service(spotify_client=spotify_client)

    albums = service.get_artist_discography("artist")

    assert len(albums) == 2
    assert albums[0]["album"]["id"] == "a1"
    assert [track["name"] for track in albums[0]["tracks"]] == ["Track", "Other"]
    assert albums[1]["album"]["name"] == "Fallback"
    assert albums[1]["tracks"][0]["name"] == "Solo"


@pytest.mark.asyncio
async def test_submit_free_ingest_uses_custom_factory() -> None:
    submit_mock = AsyncMock(return_value="submission")

    class StubFreeIngestService:
        def __init__(self) -> None:
            self.submit = submit_mock

        def get_job_status(self, job_id: str) -> None:  # pragma: no cover - not used here
            return None

    created: dict[str, Any] = {}

    def factory(config, soulseek, worker) -> StubFreeIngestService:  # type: ignore[override]
        created["worker"] = worker
        created["config"] = config
        return StubFreeIngestService()

    service = _make_service(free_ingest_factory=factory)

    result = await service.submit_free_ingest(tracks=["Track 1"])

    assert result == "submission"
    assert created["worker"] is None
    submit_mock.assert_awaited()


@pytest.mark.asyncio
async def test_enqueue_backfill_job_initialises_worker_once() -> None:
    class StubBackfillService:
        def __init__(self) -> None:
            self.created_jobs: list[Any] = []

        def create_job(self, *, max_items, expand_playlists):  # type: ignore[override]
            job = SimpleNamespace(id="job-1", limit=max_items, expand_playlists=expand_playlists)
            self.created_jobs.append(job)
            return job

        def get_status(self, job_id: str):  # pragma: no cover - not used
            return None

    class StubBackfillWorker:
        def __init__(self) -> None:
            self.started = 0
            self.enqueued: list[Any] = []

        async def start(self) -> None:
            self.started += 1

        def is_running(self) -> bool:
            return self.started > 0

        async def enqueue(self, job: Any) -> None:
            self.enqueued.append(job)

    created_worker: StubBackfillWorker | None = None

    def service_factory(config, client) -> StubBackfillService:  # type: ignore[override]
        return StubBackfillService()

    def worker_factory(service) -> StubBackfillWorker:  # type: ignore[override]
        nonlocal created_worker
        created_worker = StubBackfillWorker()
        return created_worker

    service = _make_service(
        backfill_service_factory=service_factory,
        backfill_worker_factory=worker_factory,
    )

    job = service.create_backfill_job(max_items=50, expand_playlists=True)
    await service.enqueue_backfill_job(job)
    assert created_worker is not None
    assert created_worker.started == 1
    assert created_worker.enqueued == [job]

    # second enqueue should reuse running worker
    await service.enqueue_backfill_job(job)
    assert created_worker.started == 1
    assert created_worker.enqueued == [job, job]
