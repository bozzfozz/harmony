from __future__ import annotations

import pytest

from app import dependencies as deps


@pytest.fixture(autouse=True)
def reset_watchlist_service() -> None:
    deps.get_watchlist_service.cache_clear()
    service = deps.get_watchlist_service()
    service.reset()
    yield
    service.reset()
    deps.get_watchlist_service.cache_clear()


def test_add_artist_to_watchlist(client) -> None:
    response = client.post(
        "/watchlist",
        json={"artist_key": "spotify:artist-42", "priority": 5},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["artist_key"] == "spotify:artist-42"
    assert payload["priority"] == 5

    listing = client.get("/watchlist")
    assert listing.status_code == 200
    body = listing.json()
    assert any(item["artist_key"] == "spotify:artist-42" for item in body["items"])


def test_prevent_duplicate_artists(client) -> None:
    payload = {"artist_key": "spotify:artist-99", "priority": 0}
    first = client.post("/watchlist", json=payload)
    assert first.status_code == 201

    second = client.post("/watchlist", json=payload)
    assert second.status_code == 409


def test_trimmed_identifiers_prevent_duplicates(client) -> None:
    initial = client.post(
        "/watchlist",
        json={"artist_key": "spotify:artist-777"},
    )
    assert initial.status_code == 201
    body = initial.json()
    assert body["artist_key"] == "spotify:artist-777"

    duplicate = client.post(
        "/watchlist",
        json={"artist_key": "spotify:  artist-777  "},
    )
    assert duplicate.status_code == 409
