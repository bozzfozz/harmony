from __future__ import annotations

from app.db import session_scope
from app.models import Download


def create_download(
    filename: str,
    state: str,
    priority: int = 0,
    progress: float = 0.0,
) -> int:
    with session_scope() as session:
        download = Download(
            filename=filename,
            state=state,
            progress=progress,
            priority=priority,
        )
        session.add(download)
        session.flush()
        return download.id


def test_status_filter_returns_expected_entries(client) -> None:
    queued_id = create_download("queued.mp3", "queued", priority=1)
    running_id = create_download("running.mp3", "running", priority=5)
    downloading_id = create_download(
        "downloading.mp3", "downloading", priority=4, progress=30.0
    )
    failed_id = create_download("failed.mp3", "failed")
    create_download("completed.mp3", "completed")

    response = client.get("/downloads", params={"status": "failed"})
    assert response.status_code == 200
    payload = response.json()["downloads"]
    assert {entry["id"] for entry in payload} == {failed_id}

    running_response = client.get("/downloads", params={"status": "running"})
    assert running_response.status_code == 200
    running_payload = running_response.json()["downloads"]
    running_ids = {entry["id"] for entry in running_payload}
    assert running_id in running_ids
    assert downloading_id in running_ids

    queued_response = client.get("/downloads", params={"status": "queued"})
    assert queued_response.status_code == 200
    queued_payload = queued_response.json()["downloads"]
    assert {entry["id"] for entry in queued_payload} == {queued_id}


def test_invalid_status_filter_returns_422(client) -> None:
    response = client.get("/downloads", params={"status": "unknown"})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
