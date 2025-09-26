import asyncio
import time
from datetime import datetime

from app.db import session_scope
from app.models import IngestItem, IngestJob
from app.services.backfill_service import BackfillService


def _create_job(job_id: str) -> None:
    with session_scope() as session:
        session.merge(
            IngestJob(
                id=job_id,
                source="FREE",
                state="pending",
                created_at=datetime.utcnow(),
            )
        )


def _await_backfill(
    client, worker, service: BackfillService, job_id: str, timeout: float = 2.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        client._loop.run_until_complete(asyncio.sleep(0.01))
        status = service.get_status(job_id)
        if status and status.state not in {"queued", "running"}:
            if status.state != "completed":
                raise AssertionError(f"Backfill job failed: {status.state}")
            return
    raise AssertionError(f"Backfill job {job_id} did not complete")


def test_backfill_run_endpoint(client) -> None:
    job_id = "job-router-1"
    _create_job(job_id)

    with session_scope() as session:
        item = IngestItem(
            job_id=job_id,
            source_type="FILE",
            playlist_url=None,
            raw_line="Tester - Test Song",
            artist="Tester",
            title="Test Song",
            album="Test Album",
            duration_sec=180,
            dedupe_hash="router-dedupe",
            source_fingerprint="router-fp",
            state="registered",
            created_at=datetime.utcnow(),
        )
        session.add(item)
        session.flush()
        item_id = item.id

    response = client.post(
        "/spotify/backfill/run", json={"max_items": 5, "expand_playlists": False}
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["ok"] is True
    job_identifier = payload["job_id"]

    worker = client.app.state.backfill_worker
    service = client.app.state.backfill_service
    _await_backfill(client, worker, service, job_identifier)

    status_response = client.get(f"/spotify/backfill/jobs/{job_identifier}")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["state"] == "completed"
    counts = status_payload["counts"]
    assert counts["matched"] == 1

    with session_scope() as session:
        stored = session.get(IngestItem, item_id)
        assert stored is not None
        assert stored.spotify_track_id == "track-1"


def test_backfill_run_requires_authentication(client) -> None:
    stub = client.app.state.spotify_stub
    original = stub.is_authenticated
    stub.is_authenticated = lambda: False  # type: ignore[assignment]
    try:
        response = client.post("/spotify/backfill/run", json={"max_items": 1})
        assert response.status_code == 403
    finally:
        stub.is_authenticated = original


def test_backfill_job_not_found(client) -> None:
    response = client.get("/spotify/backfill/jobs/unknown")
    assert response.status_code == 404
