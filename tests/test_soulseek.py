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
        "files": [{"filename": "song.mp3", "size": 123}],
    }
    response = client.post("/soulseek/download", json=download_payload)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    download_id = payload["detail"]["downloads"][0]["id"]

    response = client.get("/soulseek/downloads")
    assert response.status_code == 200
    downloads = response.json()["downloads"]
    download = next(item for item in downloads if item["id"] == download_id)
    assert download["state"] == "queued"
    assert download["progress"] == 0.0

    stub = client.app.state.soulseek_stub
    stub.set_status(download_id, progress=25.0, state="downloading")
    client._loop.run_until_complete(client.app.state.sync_worker.refresh_downloads())

    response = client.get("/soulseek/downloads")
    downloads = response.json()["downloads"]
    download = next(item for item in downloads if item["id"] == download_id)
    assert download["state"] == "downloading"
    assert download["progress"] > 0

    stub.set_status(download_id, progress=100.0, state="completed")
    client._loop.run_until_complete(client.app.state.sync_worker.refresh_downloads())

    response = client.get("/soulseek/downloads")
    downloads = response.json()["downloads"]
    download = next(item for item in downloads if item["id"] == download_id)
    assert download["state"] == "completed"
    assert download["progress"] == 100.0


def test_soulseek_download_cancellation(client: SimpleTestClient) -> None:
    download_payload = {
        "username": "tester",
        "files": [{"filename": "song.mp3", "size": 123}],
    }
    response = client.post("/soulseek/download", json=download_payload)
    assert response.status_code == 200
    download_id = response.json()["detail"]["downloads"][0]["id"]

    response = client.delete(f"/soulseek/download/{download_id}")
    assert response.status_code == 200
    assert response.json()["cancelled"] is True

    response = client.get("/soulseek/downloads")
    downloads = response.json()["downloads"]
    download = next(item for item in downloads if item["id"] == download_id)
    assert download["state"] == "failed"

    response = client.delete("/soulseek/download/1")
    assert response.status_code == 200
    assert response.json()["cancelled"] is True
