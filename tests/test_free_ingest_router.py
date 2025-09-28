"""Tests for the Spotify FREE ingest router."""

from __future__ import annotations

import pytest

from app.dependencies import get_app_config
from app.db import session_scope
from app.models import IngestItem, IngestJob
from tests.simple_client import SimpleTestClient


def _build_track(title: str) -> str:
    return f"Soulseek Artist - {title}"


def test_free_ingest_accepts_tracks_and_links(client: SimpleTestClient) -> None:
    response = client.post(
        "/spotify/import/free",
        json={
            "playlist_links": ["https://open.spotify.com/playlist/37i9dQZF1DX4JAvHpjipBk"],
            "tracks": [_build_track("Test Song"), _build_track("Other Track")],
        },
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["ok"] is True
    assert payload["error"] is None
    job_id = payload["job_id"]
    assert isinstance(job_id, str) and job_id.startswith("job_")
    accepted = payload["accepted"]
    assert accepted["playlists"] == 1
    assert accepted["tracks"] == 2
    assert accepted["batches"] == 1
    skipped = payload["skipped"]
    assert skipped["playlists"] == 0
    assert skipped["tracks"] == 0

    status_response = client.get(f"/spotify/import/jobs/{job_id}")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["ok"] is True
    job_data = status_payload["job"]
    assert job_data["state"] == "completed"
    counts = job_data["counts"]
    assert counts["queued"] == 2
    assert counts["normalized"] >= 1
    assert counts["failed"] == 0
    accepted_status = job_data["accepted"]
    assert accepted_status["tracks"] == 2

    with session_scope() as session:
        job_record = session.get(IngestJob, job_id)
        assert job_record is not None
        items = (
            session.query(IngestItem)
            .filter(IngestItem.job_id == job_id)
            .order_by(IngestItem.id.asc())
            .all()
        )
        assert len(items) == 3  # 1 playlist + 2 tracks
        states = {item.state for item in items}
        assert states == {"normalized", "queued"}


def test_free_ingest_rejects_invalid_playlist_host(client: SimpleTestClient) -> None:
    response = client.post(
        "/spotify/import/free",
        json={
            "playlist_links": ["https://example.com/playlist/123"],
            "tracks": [],
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["message"] == "invalid playlist links"
    details = payload["error"].get("meta", {}).get("details", [])
    assert details and details[0]["url"] == "https://example.com/playlist/123"


def test_free_ingest_enforces_track_limit(
    client: SimpleTestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FREE_MAX_TRACKS_PER_REQUEST", "3")
    get_app_config.cache_clear()
    try:
        tracks = [_build_track(f"Song {index}") for index in range(5)]
        response = client.post(
            "/spotify/import/free",
            json={"tracks": tracks},
        )
    finally:
        get_app_config.cache_clear()

    assert response.status_code == 207
    payload = response.json()
    assert payload["accepted"]["tracks"] == 3
    assert payload["skipped"]["reason"] == "limit"
    assert payload["error"] is None


def test_free_ingest_file_upload(client: SimpleTestClient) -> None:
    boundary = "----freeingest"
    lines = "\r\n".join(["Soulseek Artist - Test Song", "Soulseek Artist - Other Track"])
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="tracks.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
        f"{lines}\r\n"
        f"--{boundary}--\r\n"
    )
    response = client.post(
        "/spotify/import/free/upload",
        data=body,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"]["tracks"] == 2
