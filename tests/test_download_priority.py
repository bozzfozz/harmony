from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download, QueueJob, QueueJobStatus
from app.utils.activity import activity_manager
from app.workers.persistence import QueueJobDTO, enqueue, lease_async, update_priority
from app.workers.sync_worker import SyncWorker


class RecordingSoulseekClient:
    def __init__(self) -> None:
        self.download_calls: List[Dict[str, Any]] = []

    async def download(self, payload: Dict[str, Any]) -> None:
        self.download_calls.append(payload)

    async def get_download_status(self) -> List[Dict[str, Any]]:
        return []

    async def cancel_download(
        self, identifier: str
    ) -> None:  # pragma: no cover - unused
        return None


class BlockingRecordingSoulseekClient(RecordingSoulseekClient):
    def __init__(self) -> None:
        super().__init__()
        self.block_on_id: Optional[int] = None
        self.high_priority_id: Optional[int] = None
        self.low_started = asyncio.Event()
        self.high_started = asyncio.Event()
        self._release = asyncio.Event()

    async def download(self, payload: Dict[str, Any]) -> None:
        await super().download(payload)
        files = payload.get("files", [])
        for file_info in files:
            identifier = int(file_info.get("download_id", 0))
            if (
                self.high_priority_id is not None
                and identifier == self.high_priority_id
            ):
                self.high_started.set()
            if self.block_on_id is not None and identifier == self.block_on_id:
                self.low_started.set()
                await self._release.wait()

    def release(self) -> None:
        self._release.set()


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


@pytest.mark.asyncio
async def test_high_priority_job_preempts_recent_low_priority_lease() -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    client = RecordingSoulseekClient()

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

    low_leased = asyncio.Event()
    allow_processing = asyncio.Event()

    async def tracking_lease(
        job_id: int, job_type: str, lease_seconds: int | None
    ) -> QueueJobDTO | None:
        leased_job = await lease_async(
            job_id, job_type=job_type, lease_seconds=lease_seconds
        )
        if leased_job and any(
            isinstance(item, dict) and int(item.get("download_id", 0)) == low_id
            for item in leased_job.payload.get("files", [])
        ):
            low_leased.set()
            await allow_processing.wait()
        return leased_job

    worker = SyncWorker(client, concurrency=1, lease_fn=tracking_lease)

    await worker.start()

    try:
        await worker.enqueue(
            {
                "username": "tester",
                "files": [{"download_id": low_id, "priority": 1}],
                "priority": 1,
            }
        )

        await asyncio.wait_for(low_leased.wait(), timeout=1)

        await worker.enqueue(
            {
                "username": "tester",
                "files": [{"download_id": high_id, "priority": 10}],
                "priority": 10,
            }
        )

        allow_processing.set()
        await asyncio.sleep(0.1)
    finally:
        allow_processing.set()
        await worker.stop()

    assert len(client.download_calls) >= 2
    first = client.download_calls[0]
    second = client.download_calls[1]
    assert first["files"][0]["download_id"] == high_id
    assert second["files"][0]["download_id"] == low_id


@pytest.mark.asyncio
async def test_high_priority_arrival_during_processing_runs_next() -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    client = BlockingRecordingSoulseekClient()

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

    client.block_on_id = low_id
    client.high_priority_id = high_id
    worker = SyncWorker(client, concurrency=1)

    await worker.start()

    try:
        await worker.enqueue(
            {
                "username": "tester",
                "files": [{"download_id": low_id, "priority": 1}],
                "priority": 1,
            }
        )

        await asyncio.wait_for(client.low_started.wait(), timeout=1)

        await worker.enqueue(
            {
                "username": "tester",
                "files": [{"download_id": high_id, "priority": 10}],
                "priority": 10,
            }
        )

        client.release()
        await asyncio.wait_for(client.high_started.wait(), timeout=1)
        await asyncio.sleep(0.05)
    finally:
        client.release()
        await worker.stop()

    assert len(client.download_calls) >= 2
    first = client.download_calls[0]
    second = client.download_calls[1]
    assert first["files"][0]["download_id"] == low_id
    assert second["files"][0]["download_id"] == high_id


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

    job_payload = {
        "username": "tester",
        "files": [{"download_id": download_id, "priority": 0}],
        "priority": 0,
    }
    job = enqueue("sync", job_payload)

    with session_scope() as session:
        download = session.get(Download, download_id)
        assert download is not None
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
        refreshed_job = session.get(QueueJob, job_id)
        assert refreshed_job is not None
        assert refreshed_job.payload.get("priority") == 7
        files = refreshed_job.payload.get("files", [])
        assert files and files[0].get("priority") == 7
        assert refreshed_job.status == QueueJobStatus.PENDING.value


@pytest.mark.parametrize(
    "status",
    [QueueJobStatus.PENDING.value, QueueJobStatus.FAILED.value],
)
def test_job_queue_priority_update_allows_requeue(status: str) -> None:
    reset_engine_for_tests()
    init_db()
    job = enqueue(
        "sync",
        {"priority": 1, "files": [{"download_id": 1, "priority": 1}]},
    )

    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        db_job.status = status
        session.add(db_job)

    with session_scope() as session:
        original = session.get(QueueJob, job.id)
        assert original is not None
        original_updated_at = original.updated_at

    result = update_priority(job.id, 5, job_type="sync")
    assert result is True

    with session_scope() as session:
        refreshed = session.get(QueueJob, job.id)
        assert refreshed is not None
        assert refreshed.payload.get("priority") == 5
        assert all(
            isinstance(item, dict) and item.get("priority") == 5
            for item in refreshed.payload.get("files", [])
        )
        assert refreshed.status == QueueJobStatus.PENDING.value
        assert refreshed.updated_at >= original_updated_at


@pytest.mark.parametrize(
    "status",
    [QueueJobStatus.LEASED.value, QueueJobStatus.COMPLETED.value],
)
def test_job_queue_priority_update_rejects_disallowed_states(status: str) -> None:
    reset_engine_for_tests()
    init_db()
    job = enqueue(
        "sync",
        {"priority": 2, "files": [{"download_id": 1, "priority": 2}]},
    )

    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        db_job.status = status
        session.add(db_job)

    result = update_priority(job.id, 9, job_type="sync")
    assert result is False

    with session_scope() as session:
        refreshed = session.get(QueueJob, job.id)
        assert refreshed is not None
        assert refreshed.payload.get("priority") == 2
        assert all(
            isinstance(item, dict) and item.get("priority") == 2
            for item in refreshed.payload.get("files", [])
        )
        assert refreshed.status == status


def test_job_queue_priority_update_handles_missing_job() -> None:
    reset_engine_for_tests()
    init_db()
    result = update_priority("9999", 3, job_type="sync")
    assert result is False
