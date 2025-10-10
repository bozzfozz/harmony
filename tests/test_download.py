from __future__ import annotations

from typing import Dict, List

from app.core.transfers_api import TransfersApiError
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


def create_many_downloads(count: int) -> List[int]:
    with session_scope() as session:
        session.query(Download).delete()

        ids: List[int] = []
        for index in range(count):
            download = Download(
                filename=f"queued-{index}.mp3",
                state="queued",
                progress=float(index % 100) / 100,
            )
            session.add(download)
            session.flush()
            ids.append(download.id)

        session.commit()

        return ids


def test_download_endpoint_returns_id_and_status(client) -> None:
    payload = {
        "username": "tester",
        "files": [
            {"filename": "song.mp3", "size": 1024},
        ],
    }

    response = client.post("/download", json=payload)
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


def test_download_flow_submission_returns_handle(client) -> None:
    payload = {
        "requested_by": "tester",
        "items": [
            {"artist": "Example Artist", "title": "Example Track"},
        ],
    }

    response = client.post("/downloads", json=payload)
    assert response.status_code == 202

    body = response.json()
    assert body["items_total"] == 1
    assert body["requested_by"] == "tester"
    assert isinstance(body["batch_id"], str)
    assert body["batch_id"]


def test_download_returns_503_when_worker_missing(client) -> None:
    client.app.state.sync_worker = None

    payload = {
        "username": "tester",
        "files": [{"filename": "song.mp3"}],
    }

    response = client.post("/download", json=payload)
    assert response.status_code == 503

    entries = activity_manager.list()
    assert entries
    assert entries[0]["type"] == "download"
    assert entries[0]["status"] == "failed"
    assert entries[0]["details"]["reason"] == "worker_unavailable"


def test_get_downloads_returns_only_active_by_default(client) -> None:
    ids = create_download_samples()

    response = client.get("/downloads")
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

    response = client.get("/downloads", params={"all": "true"})
    assert response.status_code == 200

    payload = response.json()
    downloads = payload["downloads"]
    download_ids = {entry["id"] for entry in downloads}

    assert ids["queued"] in download_ids
    assert ids["running"] in download_ids
    assert ids["completed"] in download_ids

    assert activity_manager.list() == []


def test_get_downloads_uses_default_limit(client) -> None:
    ids = create_many_downloads(30)

    response = client.get("/downloads")
    assert response.status_code == 200

    downloads = response.json()["downloads"]

    assert len(downloads) == 20

    returned_ids = [entry["id"] for entry in downloads]
    expected_ids = sorted(ids, reverse=True)[:20]
    assert returned_ids == expected_ids

    created_at_values = [entry["created_at"] for entry in downloads]
    assert created_at_values == sorted(created_at_values, reverse=True)


def test_get_downloads_supports_limit_and_offset(client) -> None:
    ids = create_many_downloads(15)

    response = client.get("/downloads", params={"limit": 5, "offset": 5})
    assert response.status_code == 200

    downloads = response.json()["downloads"]
    assert len(downloads) == 5

    returned_ids = [entry["id"] for entry in downloads]
    expected_ids = sorted(ids, reverse=True)[5:10]
    assert returned_ids == expected_ids


def test_get_downloads_rejects_invalid_limit(client) -> None:
    response = client.get("/downloads", params={"limit": -1})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_get_download_detail_returns_entry(client) -> None:
    ids = create_download_samples()

    response = client.get(f"/download/{ids['running']}")
    assert response.status_code == 200

    payload = response.json()
    assert payload["id"] == ids["running"]
    assert payload["status"] == "running"
    assert payload["progress"] == 0.5

    assert activity_manager.list() == []


def test_get_download_detail_returns_404_for_unknown_id(client) -> None:
    with session_scope() as session:
        session.query(Download).delete()

    response = client.get("/download/9999")
    assert response.status_code == 404

    assert activity_manager.list() == []


def test_cancel_download_sets_state_and_activity(client) -> None:
    payload = {
        "username": "tester",
        "files": [
            {"filename": "song.mp3", "size": 512},
        ],
    }

    start_response = client.post("/download", json=payload)
    assert start_response.status_code == 202
    original_id = start_response.json()["download_id"]

    response = client.delete(f"/download/{original_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["download_id"] == original_id

    with session_scope() as session:
        download = session.get(Download, original_id)
        assert download is not None
        assert download.state == "cancelled"

    transfers_stub = client.app.state.transfers_stub
    assert original_id in transfers_stub.cancelled

    entries = activity_manager.list()
    assert entries[0]["status"] == "download_cancelled"
    assert entries[0]["details"]["download_id"] == original_id


def test_cancel_download_returns_502_when_transfers_unavailable(client) -> None:
    payload = {
        "username": "tester",
        "files": [
            {"filename": "song.mp3", "size": 512},
        ],
    }

    start_response = client.post("/download", json=payload)
    assert start_response.status_code == 202
    original_id = start_response.json()["download_id"]

    transfers_stub = client.app.state.transfers_stub
    transfers_stub.raise_cancel = TransfersApiError("offline")

    response = client.delete(f"/download/{original_id}")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "DEPENDENCY_ERROR"

    with session_scope() as session:
        download = session.get(Download, original_id)
        assert download is not None
        assert download.state == "queued"

    entries = activity_manager.list()
    assert entries
    assert entries[0]["status"] == "queued"
    assert original_id in entries[0]["details"]["download_ids"]
    assert all(entry["status"] != "download_cancelled" for entry in entries)


def test_retry_download_creates_new_entry(client) -> None:
    payload = {
        "username": "tester",
        "files": [
            {"filename": "song.mp3", "size": 512},
        ],
    }

    start_response = client.post("/download", json=payload)
    assert start_response.status_code == 202
    original_id = start_response.json()["download_id"]

    cancel_response = client.delete(f"/download/{original_id}")
    assert cancel_response.status_code == 200

    response = client.post(f"/download/{original_id}/retry")
    assert response.status_code == 202

    body = response.json()
    retry_id = body["download_id"]
    assert retry_id != original_id

    with session_scope() as session:
        retry_download = session.get(Download, retry_id)
        assert retry_download is not None
        assert retry_download.state == "queued"
        assert retry_download.username == "tester"
        assert retry_download.request_payload["download_id"] == retry_id

    transfers_stub = client.app.state.transfers_stub
    assert original_id in transfers_stub.cancelled
    assert any(
        job["files"][0]["download_id"] == retry_id for job in transfers_stub.enqueued
    )

    soulseek_stub = client.app.state.soulseek_stub
    assert soulseek_stub.downloads[original_id]["state"] == "failed"

    entries = activity_manager.list()
    assert entries[0]["status"] == "download_retried"
    assert entries[0]["details"]["retry_download_id"] == retry_id


def test_retry_download_returns_502_when_enqueue_fails(client) -> None:
    payload = {
        "username": "tester",
        "files": [
            {"filename": "song.mp3", "size": 512},
        ],
    }

    start_response = client.post("/download", json=payload)
    assert start_response.status_code == 202
    original_id = start_response.json()["download_id"]

    cancel_response = client.delete(f"/download/{original_id}")
    assert cancel_response.status_code == 200

    transfers_stub = client.app.state.transfers_stub
    transfers_stub.raise_enqueue = TransfersApiError("offline")

    response = client.post(f"/download/{original_id}/retry")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "DEPENDENCY_ERROR"

    with session_scope() as session:
        downloads = session.query(Download).all()
        assert len(downloads) == 1
        original = session.get(Download, original_id)
        assert original is not None
        assert original.state == "cancelled"

    assert transfers_stub.enqueued == []

    entries = activity_manager.list()
    assert all(entry["status"] != "download_retried" for entry in entries)


def test_retry_download_returns_502_when_cancel_fails(client) -> None:
    payload = {
        "username": "tester",
        "files": [
            {"filename": "song.mp3", "size": 512},
        ],
    }

    start_response = client.post("/download", json=payload)
    assert start_response.status_code == 202
    original_id = start_response.json()["download_id"]

    with session_scope() as session:
        download = session.get(Download, original_id)
        assert download is not None
        download.state = "failed"
        session.commit()

    transfers_stub = client.app.state.transfers_stub
    transfers_stub.raise_cancel = TransfersApiError("offline")

    response = client.post(f"/download/{original_id}/retry")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "DEPENDENCY_ERROR"

    with session_scope() as session:
        downloads = session.query(Download).all()
        assert len(downloads) == 1
        original = session.get(Download, original_id)
        assert original is not None
        assert original.state == "failed"

    assert transfers_stub.enqueued == []

    entries = activity_manager.list()
    assert all(entry["status"] != "download_retried" for entry in entries)


def test_cancel_download_rejects_invalid_state(client) -> None:
    with session_scope() as session:
        session.query(Download).delete()
        completed = Download(filename="done.mp3", state="completed", progress=1.0)
        session.add(completed)
        session.commit()
        download_id = completed.id

    response = client.delete(f"/download/{download_id}")
    assert response.status_code == 409


def test_retry_download_rejects_invalid_state(client) -> None:
    with session_scope() as session:
        session.query(Download).delete()
        queued = Download(filename="pending.mp3", state="queued", progress=0.0)
        session.add(queued)
        session.commit()
        download_id = queued.id

    response = client.post(f"/download/{download_id}/retry")
    assert response.status_code == 409


def test_retry_download_requires_payload(client) -> None:
    with session_scope() as session:
        session.query(Download).delete()
        failed = Download(filename="broken.mp3", state="failed", progress=0.0)
        session.add(failed)
        session.commit()
        download_id = failed.id

    response = client.post(f"/download/{download_id}/retry")
    assert response.status_code == 400
