from __future__ import annotations

from tests.simple_client import SimpleTestClient


def test_spotify_status(client: SimpleTestClient) -> None:
    response = client.get("/spotify/status")
    assert response.status_code == 200
    assert response.json()["status"] == "connected"


def test_spotify_search_tracks(client: SimpleTestClient) -> None:
    response = client.get("/spotify/search/tracks", params={"query": "Test"})
    assert response.status_code == 200
    body = response.json()
    assert body["items"]


def test_spotify_track_details(client: SimpleTestClient) -> None:
    response = client.get("/spotify/track/track-1")
    assert response.status_code == 200
    assert response.json()["track"]["id"] == "track-1"
