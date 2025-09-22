from __future__ import annotations

from tests.simple_client import SimpleTestClient


def test_plex_status(client: SimpleTestClient) -> None:
    response = client.get("/plex/status")
    assert response.status_code == 200
    assert response.json()["status"] == "connected"


def test_plex_artists(client: SimpleTestClient) -> None:
    response = client.get("/plex/artists")
    assert response.status_code == 200
    assert response.json()[0]["name"] == "Tester"


def test_plex_tracks(client: SimpleTestClient) -> None:
    response = client.get("/plex/album/10/tracks")
    assert response.status_code == 200
    assert response.json()[0]["title"] == "Test Song"
