from __future__ import annotations


def test_add_artist_to_watchlist(client) -> None:
    response = client.post(
        "/watchlist",
        json={"spotify_artist_id": "artist-42", "name": "Example Artist"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["spotify_artist_id"] == "artist-42"
    assert payload["name"] == "Example Artist"

    listing = client.get("/watchlist")
    assert listing.status_code == 200
    body = listing.json()
    assert any(item["spotify_artist_id"] == "artist-42" for item in body["items"])


def test_prevent_duplicate_artists(client) -> None:
    payload = {"spotify_artist_id": "artist-99", "name": "Duplicate"}
    first = client.post("/watchlist", json=payload)
    assert first.status_code == 201

    second = client.post("/watchlist", json=payload)
    assert second.status_code == 409
