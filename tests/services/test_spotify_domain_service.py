from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import load_config
from app.integrations.contracts import ProviderTrack
from app.services.free_ingest_service import IngestAccepted, IngestSkipped, IngestSubmission
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
    spotify_client.get_playlist_items.return_value = {
        "items": [
            {
                "track": {
                    "id": "t1",
                    "name": "Track One",
                    "duration_ms": 123000,
                    "artists": [{"name": "Artist One"}],
                },
                "added_at": "2024-01-01T00:00:00Z",
                "is_local": False,
                "added_by": {
                    "id": "user-1",
                    "type": "user",
                    "uri": "spotify:user:user-1",
                },
            },
            {
                "track": {
                    "id": "t2",
                    "name": "Track Two",
                    "duration_ms": 456000,
                    "artists": [{"name": "Artist Two"}],
                },
                "added_at": "2024-01-02T00:00:00Z",
            },
        ]
    }
    service = _make_service(spotify_client=spotify_client)

    result = service.get_playlist_items("playlist", limit=10)

    assert isinstance(result, PlaylistItemsResult)
    assert result.total == 2
    assert all(isinstance(item, ProviderTrack) for item in result.items)
    first_track = result.items[0]
    assert first_track.metadata["id"] == "t1"
    assert first_track.metadata["duration_ms"] == 123000
    playlist_metadata = first_track.metadata.get("playlist_item", {})
    assert playlist_metadata["added_at"] == "2024-01-01T00:00:00Z"
    assert playlist_metadata["added_by"]["id"] == "user-1"
    assert playlist_metadata["is_local"] is False


def test_search_tracks_normalizes_results() -> None:
    spotify_client = MagicMock()
    spotify_client.search_tracks.return_value = {
        "tracks": {
            "items": [
                {
                    "id": "track-1",
                    "name": "Song Title",
                    "duration_ms": 78900,
                    "artists": [
                        {
                            "id": "artist-1",
                            "name": "Artist",
                            "genres": ["rock"],
                        }
                    ],
                    "album": {
                        "id": "album-1",
                        "name": "Album",
                        "artists": [{"name": "Artist"}],
                        "release_year": 1999,
                    },
                }
            ]
        }
    }
    service = _make_service(spotify_client=spotify_client)

    results = service.search_tracks("Song Title")

    assert len(results) == 1
    track = results[0]
    assert isinstance(track, ProviderTrack)
    assert track.name == "Song Title"
    assert track.metadata["id"] == "track-1"
    assert track.metadata["duration_ms"] == 78900
    assert track.artists[0].metadata["genres"] == ("rock",)


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

    def factory(
        config, soulseek, worker, session_runner
    ) -> StubFreeIngestService:  # type: ignore[override]
        created["worker"] = worker
        created["config"] = config
        created["session_runner"] = session_runner
        return StubFreeIngestService()

    service = _make_service(free_ingest_factory=factory)

    result = await service.submit_free_ingest(tracks=["Track 1"])

    assert result == "submission"
    assert created["worker"] is None
    assert "session_runner" in created
    submit_mock.assert_awaited()


@pytest.mark.asyncio
async def test_free_import_uses_orchestrator_and_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    submission = IngestSubmission(
        ok=True,
        job_id="job-123",
        accepted=IngestAccepted(playlists=1, tracks=2, batches=1),
        skipped=IngestSkipped(playlists=0, tracks=0, reason=None),
        error=None,
    )
    captured: dict[str, Any] = {}

    async def fake_enqueue(service: SpotifyDomainService, **kwargs: Any) -> IngestSubmission:
        captured.update(kwargs)
        return submission

    events: list[dict[str, Any]] = []

    def fake_log_event(logger: Any, event: str, /, **fields: Any) -> None:
        events.append({"event": event, **fields})

    monkeypatch.setattr(
        "app.orchestrator.handlers.enqueue_spotify_free_import",
        fake_enqueue,
    )
    monkeypatch.setattr("app.services.spotify_domain_service.log_event", fake_log_event)

    service = _make_service()

    result = await service.free_import(
        playlist_links=["https://open.spotify.com/playlist/abc"],
        tracks=["Artist - Title"],
        batch_hint=10,
    )

    assert result == submission
    assert captured == {
        "playlist_links": ["https://open.spotify.com/playlist/abc"],
        "tracks": ["Artist - Title"],
        "batch_hint": 10,
    }
    matching_events = [entry for entry in events if entry.get("event") == "spotify.free_import"]
    assert matching_events, "expected spotify.free_import log event"
    logged = matching_events[0]
    assert logged["component"] == "service.spotify"
    assert logged["status"] == "ok"
    assert logged["job_id"] == submission.job_id
    assert logged["accepted_tracks"] == submission.accepted.tracks
    assert logged["skipped_tracks"] == submission.skipped.tracks
    assert "duration_ms" in logged


@pytest.mark.asyncio
async def test_enqueue_backfill_initialises_worker_once() -> None:
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
    await service.enqueue_backfill(job)
    assert created_worker is not None
    assert created_worker.started == 1
    assert created_worker.enqueued == [job]

    # second enqueue should reuse running worker
    await service.enqueue_backfill(job)
    assert created_worker.started == 1
    assert created_worker.enqueued == [job, job]
