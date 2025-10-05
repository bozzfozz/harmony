from __future__ import annotations

from tests.simple_client import SimpleTestClient


def test_soulseek_status(client: SimpleTestClient) -> None:
    response = client.get("/soulseek/status")
    assert response.status_code == 200
    assert response.json()["status"] == "connected"


def test_soulseek_search(client: SimpleTestClient) -> None:
    response = client.post("/soulseek/search", json={"query": "Test"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]
    entry = payload["results"][0]
    assert entry["files"]
    assert entry["files"][0]["title"].lower().startswith("test")


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
    payload = response.json()
    assert "retryable_states" in payload
    downloads = payload["downloads"]
    download = next(item for item in downloads if item["id"] == download_id)
    assert download["state"] == "pending"
    assert download["progress"] == 0.0

    stub = client.app.state.soulseek_stub
    stub.set_status(download_id, progress=25.0, state="downloading")
    client._loop.run_until_complete(client.app.state.sync_worker.refresh_downloads())

    response = client.get("/soulseek/downloads")
    payload = response.json()
    downloads = payload["downloads"]
    download = next(item for item in downloads if item["id"] == download_id)
    assert download["state"] == "in_progress"
    assert download["progress"] > 0

    stub.set_status(download_id, progress=100.0, state="completed")
    client._loop.run_until_complete(client.app.state.sync_worker.refresh_downloads())

    response = client.get("/soulseek/downloads")
    downloads = response.json()["downloads"]
    download = next(item for item in downloads if item["id"] == download_id)
    assert download["state"] == "completed"
    assert download["progress"] == 100.0


def test_soulseek_downloads_include_retryable_states(
    client: SimpleTestClient,
) -> None:
    response = client.get("/soulseek/downloads")
    assert response.status_code == 200

    payload = response.json()
    states = payload.get("retryable_states")

    assert isinstance(states, list)
    assert "failed" in states
    assert "completed" in states
    assert "dead_letter" not in states


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


def test_soulseek_download_management_endpoints(client: SimpleTestClient) -> None:
    payload = {
        "username": "tester",
        "files": [{"filename": "song.mp3", "size": 123}],
    }
    response = client.post("/soulseek/download", json=payload)
    assert response.status_code == 200
    download_id = response.json()["detail"]["downloads"][0]["id"]

    stub = client.app.state.soulseek_stub
    stub.queue_positions[download_id] = {"position": 3}
    stub.set_status(download_id, state="completed", progress=100.0)

    detail = client.get(f"/soulseek/download/{download_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == download_id

    queue = client.get(f"/soulseek/download/{download_id}/queue")
    assert queue.status_code == 200
    assert queue.json()["position"] == 3

    all_downloads = client.get("/soulseek/downloads/all")
    assert all_downloads.status_code == 200
    downloads = all_downloads.json()["downloads"]
    assert any(item["id"] == download_id for item in downloads)

    removed = client.delete("/soulseek/downloads/completed")
    assert removed.status_code == 200
    assert removed.json()["removed"] >= 1

    queue_after = client.get(f"/soulseek/download/{download_id}/queue")
    assert queue_after.status_code == 200


def test_soulseek_enqueue_endpoint(client: SimpleTestClient) -> None:
    payload = {
        "username": "tester",
        "files": [{"filename": "other.mp3", "size": 321}],
    }
    response = client.post("/soulseek/enqueue", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "enqueued"
    assert body["job"]["files"][0]["filename"] == "other.mp3"


def test_soulseek_upload_endpoints(client: SimpleTestClient) -> None:
    stub = client.app.state.soulseek_stub
    uploads = client.get("/soulseek/uploads")
    assert uploads.status_code == 200
    assert len(uploads.json()["uploads"]) == 1

    all_uploads = client.get("/soulseek/uploads/all")
    assert all_uploads.status_code == 200
    assert len(all_uploads.json()["uploads"]) == 2

    detail = client.get("/soulseek/upload/up-1")
    assert detail.status_code == 200
    assert detail.json()["id"] == "up-1"

    cancel = client.delete("/soulseek/upload/up-1")
    assert cancel.status_code == 200
    assert cancel.json()["cancelled"] == "up-1"

    removed = client.delete("/soulseek/uploads/completed")
    assert removed.status_code == 200
    assert removed.json()["removed"] >= 1

    assert stub.uploads["up-1"]["state"] == "cancelled"


def test_soulseek_user_endpoints(client: SimpleTestClient) -> None:
    address = client.get("/soulseek/user/tester/address")
    assert address.status_code == 200
    assert address.json()["host"] == "127.0.0.1"

    browse = client.get("/soulseek/user/tester/browse")
    assert browse.status_code == 200
    assert browse.json()["files"] == ["song.mp3"]

    status = client.get("/soulseek/user/tester/browsing_status")
    assert status.status_code == 200
    assert status.json()["state"] == "idle"

    directory = client.get("/soulseek/user/tester/directory", params={"path": "/music"})
    assert directory.status_code == 200
    assert directory.json()["path"] == "/music"

    info = client.get("/soulseek/user/tester/info")
    assert info.status_code == 200
    assert info.json()["username"] == "tester"

    user_status = client.get("/soulseek/user/tester/status")
    assert user_status.status_code == 200
    assert user_status.json()["online"] is True
