from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download, WorkerJob
from app.utils.activity import activity_manager
from app.workers.persistence import PersistentJobQueue
from app.workers.sync_worker import SyncWorker


class RecordingSoulseekClient:
    def __init__(self) -> None:
        self.download_calls: List[Dict[str, Any]] = []

    async def download(self, payload: Dict[str, Any]) -> None:
        self.download_calls.append(payload)

    async def get_download_status(self) -> List[Dict[str, Any]]:
        return []

    async def cancel_download(self, identifier: str) -> None:  # pragma: no cover - unused
        return None


@pytest.mark.asyncio
async def test_high_priority_jobs_are_processed_first() -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    client = RecordingSoulseekClient()
    worker = SyncWorker(client, concurrency=1)

    with session_scope() as session:
        low = Download(
            filename="low.mp3",
            state="queued",
            progress=0.0,
            username="tester",
            priority=1,
        )
        high = Download(
            filename="high.mp3",
            state="queued",
            progress=0.0,
            username="tester",
            priority=10,
        )
        session.add_all([low, high])
        session.flush()
        low_id = low.id
        high_id = high.id

    await worker.start()

    await worker.enqueue(
        {
            "username": "tester",
            "files": [{"download_id": low_id, "priority": 1}],
            "priority": 1,
        }
    )
    await worker.enqueue(
        {
            "username": "tester",
            "files": [{"download_id": high_id, "priority": 10}],
            "priority": 10,
        }
    )

    await asyncio.sleep(0.05)
    await worker.stop()

    assert len(client.download_calls) >= 2
    first_call = client.download_calls[0]
    first_download_id = first_call["files"][0]["download_id"]
    assert first_download_id == high_id


def test_priority_can_be_updated_via_api(client) -> None:
    with session_scope() as session:
        download = Download(
            filename="adjustable.mp3",
            state="queued",
            progress=0.0,
            username="tester",
            priority=0,
        )
        session.add(download)
        session.flush()
        download_id = download.id
        job = WorkerJob(
            worker="sync",
            payload={
                "username": "tester",
                "files": [{"download_id": download_id, "priority": 0}],
                "priority": 0,
            },
            state="queued",
        )
        session.add(job)
        session.flush()
        download.job_id = str(job.id)
        payload_copy = dict(download.request_payload or {})
        payload_copy.update({"download_id": download_id, "priority": 0})
        download.request_payload = payload_copy
        session.add(download)
        job_id = job.id

    response = client.patch(
        f"/download/{download_id}/priority",
        json={"priority": 7},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["priority"] == 7

    detail_response = client.get(f"/download/{download_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["priority"] == 7
    assert detail["status"] == "pending"

    with session_scope() as session:
        refreshed_download = session.get(Download, download_id)
        assert refreshed_download is not None
        assert refreshed_download.request_payload.get("priority") == 7
        refreshed_job = session.get(WorkerJob, job_id)
        assert refreshed_job is not None
        assert refreshed_job.payload.get("priority") == 7
        files = refreshed_job.payload.get("files", [])
        assert files and files[0].get("priority") == 7
        assert refreshed_job.state == "queued"


@pytest.mark.parametrize("state", ["queued", "retrying"])
def test_job_queue_priority_update_allows_requeue(state: str) -> None:
    reset_engine_for_tests()
    init_db()
    queue = PersistentJobQueue("sync")

    with session_scope() as session:
        job = WorkerJob(
            worker="sync",
            payload={
                "priority": 1,
                "files": [{"download_id": 1, "priority": 1}],
            },
            state=state,
        )
        session.add(job)
        session.flush()
        job_id = str(job.id)
        original_updated_at = job.updated_at

    result = queue.update_priority(job_id, 5)
    assert result is True

    with session_scope() as session:
        refreshed = session.get(WorkerJob, int(job_id))
        assert refreshed is not None
        assert refreshed.payload.get("priority") == 5
        assert all(
            isinstance(item, dict) and item.get("priority") == 5
            for item in refreshed.payload.get("files", [])
        )
        assert refreshed.state == "queued"
        assert refreshed.updated_at >= original_updated_at


@pytest.mark.parametrize("state", ["running", "completed"])
def test_job_queue_priority_update_rejects_disallowed_states(state: str) -> None:
    reset_engine_for_tests()
    init_db()
    queue = PersistentJobQueue("sync")

    with session_scope() as session:
        job = WorkerJob(
            worker="sync",
            payload={
                "priority": 2,
                "files": [{"download_id": 1, "priority": 2}],
            },
            state=state,
        )
        session.add(job)
        session.flush()
        job_id = str(job.id)

    result = queue.update_priority(job_id, 9)
    assert result is False

    with session_scope() as session:
        refreshed = session.get(WorkerJob, int(job_id))
        assert refreshed is not None
        assert refreshed.payload.get("priority") == 2
        assert all(
            isinstance(item, dict) and item.get("priority") == 2
            for item in refreshed.payload.get("files", [])
        )
        assert refreshed.state == state


def test_job_queue_priority_update_handles_missing_job() -> None:
    reset_engine_for_tests()
    init_db()
    queue = PersistentJobQueue("sync")

    result = queue.update_priority("9999", 3)
    assert result is False
