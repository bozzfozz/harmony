from __future__ import annotations

from tests.simple_client import SimpleTestClient


def test_soulseek_status(client: SimpleTestClient) -> None:
    response = client.get("/soulseek/status")
    assert response.status_code == 200
    assert response.json()["status"] == "connected"


def test_soulseek_search(client: SimpleTestClient) -> None:
    response = client.post("/soulseek/search", json={"query": "Test"})
    assert response.status_code == 200
    assert response.json()["results"] == ["Test"]


def test_soulseek_download_flow(client: SimpleTestClient) -> None:
    download_payload = {
        "username": "tester",
        "files": [{"filename": "song.mp3", "size": 123}]
    }
    response = client.post("/soulseek/download", json=download_payload)
    assert response.status_code == 200
    assert response.json()["status"] == "queued"

    response = client.get("/soulseek/downloads")
    assert response.status_code == 200
    assert response.json()["downloads"] == []

    response = client.delete("/soulseek/download/1")
    assert response.status_code == 200
    assert response.json()["cancelled"] is True
