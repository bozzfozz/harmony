from __future__ import annotations

from tests.simple_client import SimpleTestClient


def test_spotify_mode_defaults(client: SimpleTestClient) -> None:
    response = client.get("/spotify/mode")
    assert response.status_code == 200
    assert response.json()["mode"] == "PRO"


def test_spotify_mode_switch(client: SimpleTestClient) -> None:
    response = client.post("/spotify/mode", json={"mode": "FREE"})
    assert response.status_code == 200
    assert response.json()["ok"] is True

    updated = client.get("/spotify/mode")
    assert updated.status_code == 200
    assert updated.json()["mode"] == "FREE"
