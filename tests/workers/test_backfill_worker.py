import asyncio

import pytest

from app.services.backfill_service import BackfillJobSpec
from app.workers import backfill_worker as worker_module
from app.workers.backfill_worker import BackfillWorker


class StubBackfillService:
    def __init__(self) -> None:
        self.executed: list[BackfillJobSpec] = []

    async def execute(self, job: BackfillJobSpec) -> None:
        await asyncio.sleep(0)
        self.executed.append(job)


@pytest.mark.asyncio
async def test_backfill_worker_processes_jobs_enqueued_before_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubBackfillService()
    worker = BackfillWorker(service)

    monkeypatch.setattr(worker_module, "record_worker_started", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_module, "mark_worker_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_module, "record_worker_heartbeat", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_module, "record_worker_stopped", lambda *args, **kwargs: None)

    job = BackfillJobSpec(id="job-1", limit=1, expand_playlists=False)

    await worker.enqueue(job)

    assert service.executed == []

    await worker.start()
    await asyncio.wait_for(worker.wait_until_idle(), timeout=1)

    assert service.executed == [job]

    await worker.stop()


@pytest.mark.asyncio
async def test_backfill_worker_preserves_queue_across_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubBackfillService()
    worker = BackfillWorker(service)

    monkeypatch.setattr(worker_module, "record_worker_started", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_module, "mark_worker_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_module, "record_worker_heartbeat", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker_module, "record_worker_stopped", lambda *args, **kwargs: None)

    original_run = worker_module.BackfillWorker._run
    start_gate = asyncio.Event()

    async def gated_run(self: BackfillWorker, queue: asyncio.Queue[BackfillJobSpec]) -> None:
        await start_gate.wait()
        await original_run(self, queue)

    monkeypatch.setattr(worker_module.BackfillWorker, "_run", gated_run)

    job = BackfillJobSpec(id="job-preserved", limit=1, expand_playlists=False)

    await worker.enqueue(job)
    await worker.start()

    # Allow the worker task to reach the gate before stopping it again.
    await asyncio.sleep(0)

    assert service.executed == []

    await worker.stop()

    # The job should not have been processed while the worker was stopped.
    assert service.executed == []

    start_gate.set()

    await worker.start()
    await asyncio.wait_for(worker.wait_until_idle(), timeout=1)

    assert service.executed == [job]

    await worker.stop()
