"""Regression tests for the download router error envelope."""

from __future__ import annotations

from typing import Any

from tests.helpers import api_path
from tests.simple_client import SimpleTestClient

from app.core.transfers_api import TransfersDependencyError
from app.db import session_scope
from app.models import Download


def _create_download(*, state: str = "queued", **overrides: Any) -> int:
    with session_scope() as session:
        record = Download(
            filename=overrides.get("filename", "sample.mp3"),
            state=state,
            progress=overrides.get("progress", 0.0),
            username=overrides.get("username", "tester"),
            priority=overrides.get("priority", 1),
        )
        request_payload = overrides.get("request_payload")
        if request_payload is not None:
            record.request_payload = dict(request_payload)
        session.add(record)
        session.flush()
        download_id = record.id
    return download_id


def test_start_download_without_files_returns_validation_error(
    client: SimpleTestClient,
) -> None:
    payload = {"username": "tester", "files": []}

    response = client.post(api_path("/download"), json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "No files supplied"


def test_start_download_missing_username_returns_422(client: SimpleTestClient) -> None:
    payload = {"files": [{"filename": "track.mp3"}]}

    response = client.post(api_path("/download"), json=payload)

    assert response.status_code == 422


def test_start_download_invalid_file_entry_returns_422(
    client: SimpleTestClient,
) -> None:
    payload = {"username": "tester", "files": [{"priority": "high"}]}

    response = client.post(api_path("/download"), json=payload)

    assert response.status_code == 422


def test_get_download_not_found_returns_standard_error(
    client: SimpleTestClient,
) -> None:
    response = client.get(api_path("/download/999999"))

    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "Download not found"


def test_cancel_download_dependency_failure_maps_to_error_envelope(
    client: SimpleTestClient,
) -> None:
    download_id = _create_download(state="queued")
    stub = client.app.state.transfers_stub
    stub.raise_cancel = TransfersDependencyError(
        "slskd unavailable", status_code=503, details={"hint": "retry"}
    )

    try:
        response = client.delete(api_path(f"/download/{download_id}"))
    finally:
        stub.raise_cancel = None

    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "DEPENDENCY_ERROR"
    assert body["error"]["message"] == "slskd unavailable"
    assert body["error"].get("meta") == {
        "provider": "slskd",
        "hint": "retry",
        "status_code": 503,
    }


def test_retry_download_invalid_state_returns_validation_error(
    client: SimpleTestClient,
) -> None:
    download_id = _create_download(
        state="queued", request_payload={"filename": "song.mp3"}
    )

    response = client.post(api_path(f"/download/{download_id}/retry"))

    assert response.status_code == 409
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Download cannot be retried in its current state"
