from __future__ import annotations

from datetime import datetime, timezone

import pytest
from tests.helpers import api_path
from tests.simple_client import SimpleTestClient

from app import dependencies as deps
from app.main import app


@pytest.fixture(autouse=True)
def reset_watchlist_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")
    monkeypatch.setenv("FEATURE_REQUIRE_AUTH", "0")
    deps.get_watchlist_service.cache_clear()
    service = deps.get_watchlist_service()
    service.reset()
    app.openapi_schema = None
    yield
    service.reset()
    deps.get_watchlist_service.cache_clear()
    app.openapi_schema = None


def test_watchlist_crud_flow() -> None:
    with SimpleTestClient(app) as client:
        created = client.post(
            api_path("/watchlist"),
            json={"artist_key": "spotify:alpha", "priority": 7},
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["artist_key"] == "spotify:alpha"
        assert payload["priority"] == 7
        assert payload["paused"] is False

        listing = client.get(api_path("/watchlist"))
        assert listing.status_code == 200
        body = listing.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["artist_key"] == "spotify:alpha"

        updated = client.patch(
            api_path("/watchlist/spotify:alpha"),
            json={"priority": 42},
        )
        assert updated.status_code == 200
        assert updated.json()["priority"] == 42

        deleted = client.delete(api_path("/watchlist/spotify:alpha"))
        assert deleted.status_code == 204

        after = client.get(api_path("/watchlist"))
        assert after.status_code == 200
        assert after.json()["items"] == []


def test_watchlist_pause_and_resume() -> None:
    resume_time = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    with SimpleTestClient(app) as client:
        client.post(
            api_path("/watchlist"),
            json={"artist_key": "spotify:beta", "priority": 3},
        )

        paused = client.post(
            api_path("/watchlist/spotify:beta/pause"),
            json={"reason": "manual", "resume_at": resume_time.isoformat()},
        )
        assert paused.status_code == 200
        pause_body = paused.json()
        assert pause_body["paused"] is True
        assert pause_body["pause_reason"] == "manual"
        resumed_at = datetime.fromisoformat(
            pause_body["resume_at"].replace("Z", "+00:00")
        )
        assert resumed_at == resume_time

        resumed = client.post(api_path("/watchlist/spotify:beta/resume"))
        assert resumed.status_code == 200
        resume_body = resumed.json()
        assert resume_body["paused"] is False
        assert resume_body["pause_reason"] is None
        assert resume_body["resume_at"] is None
