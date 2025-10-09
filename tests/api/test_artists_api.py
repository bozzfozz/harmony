from __future__ import annotations

from datetime import datetime

import pytest
from tests.helpers import api_path
from tests.simple_client import SimpleTestClient
from tests.support.postgres import postgres_schema

from app import dependencies as deps
from app.db import init_db, reset_engine_for_tests, session_scope
from app.main import app
from app.models import QueueJob
from app.services.artist_dao import (
    ArtistDao,
    ArtistReleaseUpsertDTO,
    ArtistUpsertDTO,
    build_artist_key,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")
    monkeypatch.setenv("FEATURE_REQUIRE_AUTH", "0")
    with postgres_schema("artists", monkeypatch=monkeypatch):
        reset_engine_for_tests()
        init_db()
        deps.get_app_config.cache_clear()
        deps.get_artist_service.cache_clear()
        app.openapi_schema = None
        try:
            yield
        finally:
            deps.get_app_config.cache_clear()
            deps.get_artist_service.cache_clear()
            app.openapi_schema = None
            reset_engine_for_tests()


def _seed_artist_with_release() -> str:
    dao = ArtistDao(now_factory=lambda: datetime(2024, 1, 1, 12, 0, 0))
    artist_key = build_artist_key("spotify", "artist-1")
    dao.upsert_artist(
        ArtistUpsertDTO(
            artist_key=artist_key,
            source="spotify",
            source_id="artist-1",
            name="Example Artist",
            genres=("indie", "rock"),
            images=("https://img/1",),
            metadata={"origin": "tests"},
        )
    )
    dao.upsert_releases(
        [
            ArtistReleaseUpsertDTO(
                artist_key=artist_key,
                source="spotify",
                source_id="release-1",
                title="Debut",
                release_date="2024-01-01",
                release_type="album",
                total_tracks=10,
            )
        ]
    )
    return artist_key


def test_get_artist_returns_artist_and_releases() -> None:
    artist_key = _seed_artist_with_release()

    with SimpleTestClient(app) as client:
        response = client.get(api_path(f"/artists/{artist_key}"))

    assert response.status_code == 200
    body = response.json()
    assert body["artist_key"] == artist_key
    assert body["name"] == "Example Artist"
    assert body["genres"] == ["indie", "rock"]
    assert body["metadata"]["origin"] == "tests"
    assert len(body["releases"]) == 1
    release = body["releases"][0]
    assert release["title"] == "Debut"
    assert release["release_type"] == "album"
    assert release["total_tracks"] == 10


def test_enqueue_sync_is_idempotent_returns_202() -> None:
    artist_key = build_artist_key("spotify", "queued")
    path = api_path(f"/artists/{artist_key}/enqueue-sync")

    with SimpleTestClient(app) as client:
        first = client.post(path)
        second = client.post(path)

    assert first.status_code == 202
    assert second.status_code == 202

    first_body = first.json()
    second_body = second.json()
    assert first_body["already_enqueued"] is False
    assert second_body["already_enqueued"] is True
    assert second_body["job_id"] == first_body["job_id"]

    with session_scope() as session:
        job = session.get(QueueJob, int(first_body["job_id"]))
        assert job is not None
        assert job.type == "artist_sync"


def test_enqueue_sync_force_creates_new_job() -> None:
    artist_key = build_artist_key("spotify", "force-refresh")
    path = api_path(f"/artists/{artist_key}/enqueue-sync")

    with SimpleTestClient(app) as client:
        initial = client.post(path)
        forced = client.post(path, json={"force": True})

    assert initial.status_code == 202
    assert forced.status_code == 202

    initial_body = initial.json()
    forced_body = forced.json()
    assert initial_body["already_enqueued"] is False
    assert forced_body["already_enqueued"] is False
    assert forced_body["job_id"] != initial_body["job_id"]


def test_error_mapping_not_found_and_validation() -> None:
    with SimpleTestClient(app) as client:
        missing_response = client.get(api_path("/artists/spotify:missing"))

    assert missing_response.status_code == 404
    missing_body = missing_response.json()
    assert missing_body == {
        "ok": False,
        "error": {"code": "NOT_FOUND", "message": "Artist not found."},
    }

    with SimpleTestClient(app) as client:
        invalid = client.post(
            api_path("/artists/watchlist"),
            json={"artist_key": " ", "priority": 1},
        )

    assert invalid.status_code == 400
    body = invalid.json()
    assert body == {
        "ok": False,
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "artist_key must not be empty.",
        },
    }
