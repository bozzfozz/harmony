from datetime import datetime
from typing import Any, Dict

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import Download, QueueJob, QueueJobStatus
from app.workers import persistence


@pytest.mark.lifespan_workers
def test_e2e_download_dispatcher_executes(client) -> None:
    runtime = getattr(client.app.state, "orchestrator_runtime", None)
    assert runtime is not None, "expected orchestrator runtime to be initialised"

    dispatcher = runtime.dispatcher
    scheduler = runtime.scheduler

    processed: list[int] = []

    original_handler = dispatcher._handlers.get("sync")

    async def fake_sync_handler(job) -> Dict[str, Any]:
        processed.append(int(job.id))
        now = datetime.utcnow()
        with session_scope() as session:
            for file_info in job.payload.get("files", []):
                identifier = file_info.get("download_id")
                if identifier is None:
                    continue
                download = session.get(Download, int(identifier))
                if download is None:
                    continue
                download.state = "completed"
                download.progress = 100.0
                download.updated_at = now
                session.add(download)
        return {"status": "ok", "processed": job.id}

    dispatcher._handlers["sync"] = fake_sync_handler

    try:
        payload = {
            "username": "smoke-user",
            "files": [{"filename": "smoke.mp3"}],
        }

        response = client.post("/download", json=payload)
        assert response.status_code == 202

        with session_scope() as session:
            queued_jobs = session.execute(select(QueueJob)).scalars().all()
        assert queued_jobs, "expected queue job to be persisted"
        assert queued_jobs[0].status == QueueJobStatus.PENDING.value

        ready_jobs = persistence.fetch_ready("sync")
        assert ready_jobs, "expected pending sync job before dispatcher drains"

        client._loop.run_until_complete(dispatcher.drain_once())
    finally:
        if original_handler is not None:
            dispatcher._handlers["sync"] = original_handler

    assert processed, "expected dispatcher to process at least one job"
    leased_job_id = processed[0]

    downloads_response = client.get("/downloads", params={"all": "true"})
    assert downloads_response.status_code == 200
    downloads_payload = downloads_response.json()["downloads"]
    assert downloads_payload
    download_entry = downloads_payload[0]
    assert download_entry["status"] == "completed"
    assert download_entry["progress"] == 100.0
    assert download_entry["username"] == "smoke-user"

    with session_scope() as session:
        job_record = session.get(QueueJob, leased_job_id)
        assert job_record is not None
        assert job_record.status == QueueJobStatus.COMPLETED.value

    activity_response = client.get("/activity")
    assert activity_response.status_code == 200
    activity_items = activity_response.json()["items"]
    assert any(
        item["type"] == "download" and item["status"] == "queued"
        for item in activity_items
    )


@pytest.mark.lifespan_workers
def test_dispatcher_missing_handler_moves_job_to_dlq(client) -> None:
    runtime = getattr(client.app.state, "orchestrator_runtime", None)
    assert runtime is not None, "expected orchestrator runtime to be initialised"

    dispatcher = runtime.dispatcher
    scheduler = runtime.scheduler

    missing_handler = dispatcher._handlers.pop("matching", None)
    try:
        enqueued = persistence.enqueue("matching", {"reason": "test-missing-handler"})
        ready_jobs = persistence.fetch_ready("matching")
        assert any(job.id == enqueued.id for job in ready_jobs)

        client._loop.run_until_complete(dispatcher.drain_once())
    finally:
        if missing_handler is not None:
            dispatcher._handlers["matching"] = missing_handler

    assert scheduler.leased_jobs, "expected scheduler to record leased jobs"
    assert any(job.id == enqueued.id for job in scheduler.leased_jobs[-1])

    assert all(job.id != enqueued.id for job in dispatcher.processed_jobs)

    with session_scope() as session:
        job_record = session.get(QueueJob, enqueued.id)
        assert job_record is not None
        assert job_record.status == QueueJobStatus.CANCELLED.value
        assert job_record.last_error == "handler_missing"

    remaining_ready = persistence.fetch_ready("matching")
    assert all(job.id != enqueued.id for job in remaining_ready)
