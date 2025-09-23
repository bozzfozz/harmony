from __future__ import annotations

from app.utils.activity import activity_manager


def test_download_endpoint_returns_id_and_status(client) -> None:
    payload = {
        "username": "tester",
        "files": [
            {"filename": "song.mp3", "size": 1024},
        ],
    }

    response = client.post("/api/download", json=payload)
    assert response.status_code == 202

    body = response.json()
    assert body["status"] == "queued"
    assert body["download_id"] > 0
    assert body["downloads"][0]["filename"] == "song.mp3"

    stub = client.app.state.soulseek_stub
    assert body["download_id"] in stub.downloads

    entries = activity_manager.list()
    assert entries
    assert entries[0]["type"] == "download"
    assert entries[0]["status"] == "queued"
    assert body["download_id"] in entries[0]["details"]["download_ids"]


def test_download_returns_503_when_worker_missing(client) -> None:
    client.app.state.sync_worker = None

    payload = {
        "username": "tester",
        "files": [{"filename": "song.mp3"}],
    }

    response = client.post("/api/download", json=payload)
    assert response.status_code == 503

    entries = activity_manager.list()
    assert entries
    assert entries[0]["type"] == "download"
    assert entries[0]["status"] == "failed"
    assert entries[0]["details"]["reason"] == "worker_unavailable"
