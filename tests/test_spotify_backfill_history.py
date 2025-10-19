from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.spotify import backfill_router, _get_spotify_service
from app.services.backfill_service import BackfillJobRecord


class StubSpotifyDomainService:
    def __init__(self, jobs: list[BackfillJobRecord]) -> None:
        self._jobs = jobs
        self.calls: list[int] = []

    def list_backfill_jobs(self, *, limit: int = 10) -> list[BackfillJobRecord]:
        self.calls.append(limit)
        return self._jobs


def _build_app(service: StubSpotifyDomainService) -> FastAPI:
    app = FastAPI()
    app.include_router(backfill_router)
    app.dependency_overrides[_get_spotify_service] = lambda: service
    return app


def test_backfill_history_endpoint_returns_records() -> None:
    jobs = [
        BackfillJobRecord(
            id="job-a",
            state="completed",
            requested_items=20,
            processed_items=20,
            matched_items=15,
            cache_hits=10,
            cache_misses=2,
            expanded_playlists=1,
            expanded_tracks=5,
            expand_playlists=False,
            duration_ms=1200,
            error=None,
            created_at=datetime(2023, 6, 1, 8, 0, 0),
            updated_at=datetime(2023, 6, 1, 8, 5, 0),
        ),
        BackfillJobRecord(
            id="job-b",
            state="running",
            requested_items=40,
            processed_items=5,
            matched_items=4,
            cache_hits=1,
            cache_misses=0,
            expanded_playlists=0,
            expanded_tracks=0,
            expand_playlists=True,
            duration_ms=None,
            error=None,
            created_at=datetime(2023, 7, 1, 9, 30, 0),
            updated_at=datetime(2023, 7, 1, 9, 31, 0),
        ),
    ]
    service = StubSpotifyDomainService(jobs)
    app = _build_app(service)
    client = TestClient(app)

    response = client.get("/spotify/backfill/jobs", params={"limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["jobs"]) == 2
    assert payload["jobs"][0]["job_id"] == "job-a"
    assert payload["jobs"][1]["job_id"] == "job-b"
    assert service.calls == [5]


def test_backfill_history_endpoint_handles_empty() -> None:
    service = StubSpotifyDomainService([])
    app = _build_app(service)
    client = TestClient(app)

    response = client.get("/spotify/backfill/jobs")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"ok": True, "jobs": []}
    assert service.calls == [10]
