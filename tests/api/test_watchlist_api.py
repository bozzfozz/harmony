from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from app import dependencies as deps
from app.db import init_db, reset_engine_for_tests
from app.main import app
from tests.helpers import api_path
from tests.simple_client import SimpleTestClient


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")
    monkeypatch.setenv("FEATURE_REQUIRE_AUTH", "0")
    db_fd, db_file = tempfile.mkstemp(prefix="harmony-watchlist-", suffix=".db")
    os.close(db_fd)
    db_path = Path(db_file)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_engine_for_tests()
    if db_path.exists():
        db_path.unlink()
    init_db()
    deps.get_app_config.cache_clear()
    deps.get_artist_service.cache_clear()
    app.openapi_schema = None
    yield
    deps.get_app_config.cache_clear()
    deps.get_artist_service.cache_clear()
    app.openapi_schema = None
    reset_engine_for_tests()
    if db_path.exists():
        db_path.unlink()


def test_watchlist_crud_add_list_delete() -> None:
    with SimpleTestClient(app) as client:
        created = client.post(
            api_path("/artists/watchlist"),
            json={"artist_key": "spotify:alpha", "priority": 7},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["artist_key"] == "spotify:alpha"
        assert body["priority"] == 7

        listing = client.get(api_path("/artists/watchlist"))
        assert listing.status_code == 200
        items = listing.json()
        assert items["total"] == 1
        assert items["items"][0]["artist_key"] == "spotify:alpha"

        deleted = client.delete(api_path("/artists/watchlist/spotify:alpha"))
        assert deleted.status_code == 204

        after = client.get(api_path("/artists/watchlist"))
        assert after.status_code == 200
        assert after.json()["items"] == []


def test_watchlist_pagination_and_sorting_by_priority() -> None:
    first_cooldown = datetime(2024, 1, 1, 12, 0, 0)

    with SimpleTestClient(app) as client:
        client.post(
            api_path("/artists/watchlist"), json={"artist_key": "spotify:one", "priority": 10}
        )
        client.post(
            api_path("/artists/watchlist"),
            json={
                "artist_key": "spotify:two",
                "priority": 10,
                "cooldown_until": first_cooldown.isoformat(),
            },
        )
        client.post(
            api_path("/artists/watchlist"), json={"artist_key": "spotify:three", "priority": 5}
        )

        first_page = client.get(
            api_path("/artists/watchlist"),
            params={"limit": 2, "offset": 0},
        )
        assert first_page.status_code == 200
        payload = first_page.json()
        assert payload["total"] == 3
        assert payload["limit"] == 2
        assert [item["artist_key"] for item in payload["items"]] == [
            "spotify:one",
            "spotify:two",
        ]

        second_page = client.get(
            api_path("/artists/watchlist"),
            params={"limit": 2, "offset": 2},
        )
        assert second_page.status_code == 200
        payload = second_page.json()
        assert payload["total"] == 3
        assert [item["artist_key"] for item in payload["items"]] == ["spotify:three"]
