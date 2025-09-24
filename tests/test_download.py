from __future__ import annotations

from typing import Dict

from app.db import session_scope
from app.models import Download
from app.utils.activity import activity_manager


def create_download_samples() -> Dict[str, int]:
    with session_scope() as session:
        session.query(Download).delete()

        queued = Download(filename="queued.mp3", state="queued", progress=0.0)
        running = Download(filename="running.mp3", state="running", progress=0.5)
        completed = Download(filename="done.mp3", state="completed", progress=1.0)

        session.add_all([queued, running, completed])
        session.flush()

        return {"queued": queued.id, "running": running.id, "completed": completed.id}


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


def test_get_downloads_returns_only_active_by_default(client) -> None:
    ids = create_download_samples()

    response = client.get("/api/downloads")
    assert response.status_code == 200

    payload = response.json()
    downloads = payload["downloads"]
    download_ids = {entry["id"] for entry in downloads}

    assert ids["queued"] in download_ids
    assert ids["running"] in download_ids
    assert ids["completed"] not in download_ids

    assert activity_manager.list() == []


def test_get_downloads_can_include_completed_entries(client) -> None:
    ids = create_download_samples()

    response = client.get("/api/downloads", params={"all": "true"})
    assert response.status_code == 200

    payload = response.json()
    downloads = payload["downloads"]
    download_ids = {entry["id"] for entry in downloads}

    assert ids["queued"] in download_ids
    assert ids["running"] in download_ids
    assert ids["completed"] in download_ids

    assert activity_manager.list() == []


def test_get_download_detail_returns_entry(client) -> None:
    ids = create_download_samples()

    response = client.get(f"/api/download/{ids['running']}")
    assert response.status_code == 200

    payload = response.json()
    assert payload["id"] == ids["running"]
    assert payload["status"] == "running"
    assert payload["progress"] == 0.5

    assert activity_manager.list() == []


def test_get_download_detail_returns_404_for_unknown_id(client) -> None:
    with session_scope() as session:
        session.query(Download).delete()

    response = client.get("/api/download/9999")
    assert response.status_code == 404

    assert activity_manager.list() == []
