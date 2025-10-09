import asyncio
from datetime import datetime
from typing import Any, Dict, List

import pytest

from app.db import init_db, reset_engine_for_tests
from app.models import QueueJobStatus
from app.workers.persistence import QueueJobDTO
from app.workers.sync_worker import SyncWorker, _PriorityQueueEntry
from tests.workers.test_sync_worker import RecordingSoulseekClient


@pytest.mark.asyncio
async def test_sync_worker_prefers_new_high_priority_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later higher-priority job should preempt lower priority work waiting to start."""

    reset_engine_for_tests()
    init_db()

    client = RecordingSoulseekClient()
    processed: List[str] = []
    processed_event = asyncio.Event()

    async def fake_process_job(self: SyncWorker, payload: Dict[str, Any]) -> None:
        processed.append(payload.get("label", ""))
        if len(processed) >= 2:
            processed_event.set()

    monkeypatch.setattr(SyncWorker, "_process_job", fake_process_job)

    worker = SyncWorker(client, concurrency=1)

    original_preempt = SyncWorker._maybe_take_preempting_job
    gate = asyncio.Event()
    release_gate = asyncio.Event()
    first_call = True

    async def gated_preempt(self: SyncWorker, current_priority: int):
        nonlocal first_call
        if first_call:
            first_call = False
            gate.set()
            await release_gate.wait()
        return await original_preempt(self, current_priority)

    monkeypatch.setattr(SyncWorker, "_maybe_take_preempting_job", gated_preempt)

    try:
        await worker.start()
        await asyncio.sleep(0)

        await worker.enqueue(
            {
                "username": "tester",
                "files": [{"download_id": 1, "priority": 1}],
                "priority": 1,
                "label": "low",
            }
        )

        await asyncio.wait_for(gate.wait(), timeout=1.0)

        await worker.enqueue(
            {
                "username": "tester",
                "files": [{"download_id": 2, "priority": 10}],
                "priority": 10,
                "label": "high",
            }
        )

        release_gate.set()

        await asyncio.wait_for(processed_event.wait(), timeout=2.0)
        await asyncio.wait_for(worker.queue.join(), timeout=2.0)
    finally:
        release_gate.set()
        await worker.stop()

    assert processed[:2] == ["high", "low"]
    assert len(processed) >= 2


def _make_queue_job(*, job_id: int, priority: int) -> QueueJobDTO:
    return QueueJobDTO(
        id=job_id,
        type="sync",
        payload={},
        priority=priority,
        attempts=0,
        available_at=datetime.utcnow(),
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key=None,
    )


@pytest.mark.asyncio
async def test_maybe_take_preempting_job_returns_when_candidate_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = SyncWorker(RecordingSoulseekClient(), concurrency=1)
    job = _make_queue_job(job_id=1, priority=10)
    candidate = _PriorityQueueEntry(queue_priority=-10, sequence=0, job=job)

    def fake_peek(
        self: SyncWorker, current_priority: int
    ) -> _PriorityQueueEntry | None:
        return candidate

    monkeypatch.setattr(SyncWorker, "_peek_higher_priority_entry", fake_peek)

    result = await asyncio.wait_for(worker._maybe_take_preempting_job(0), timeout=0.1)

    assert result is None
    assert worker.queue.qsize() == 0


@pytest.mark.asyncio
async def test_maybe_take_preempting_job_requeues_lower_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = SyncWorker(RecordingSoulseekClient(), concurrency=1)
    job = _make_queue_job(job_id=2, priority=1)
    await worker._put_job(job)
    candidate = _PriorityQueueEntry(queue_priority=-10, sequence=0, job=job)

    def fake_peek(
        self: SyncWorker, current_priority: int
    ) -> _PriorityQueueEntry | None:
        return candidate

    monkeypatch.setattr(SyncWorker, "_peek_higher_priority_entry", fake_peek)

    result = await asyncio.wait_for(worker._maybe_take_preempting_job(-1), timeout=0.1)

    assert result is None
    assert worker.queue.qsize() == 1

    _, _, queued_job = worker.queue.get_nowait()
    assert queued_job is job
    worker.queue.task_done()
