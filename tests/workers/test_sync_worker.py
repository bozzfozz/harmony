from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime
from typing import Any, Dict, List

import pytest

from app.db import init_db, reset_engine_for_tests
from app.workers.persistence import (
    complete_async,
    enqueue_async,
    fail_async,
    fetch_ready_async,
    lease_async,
    release_active_leases_async,
)
from app.workers.sync_worker import SyncWorker


class RecordingSoulseekClient:
    """Soulseek client stub tracking download and poll operations."""

    def __init__(self) -> None:
        self.download_calls: List[Dict[str, Any]] = []
        self.status_calls = 0

    async def download(self, payload: Dict[str, Any]) -> None:
        self.download_calls.append(payload)

    async def get_download_status(self) -> List[Dict[str, Any]]:
        self.status_calls += 1
        return []

    async def cancel_download(
        self, identifier: str
    ) -> None:  # pragma: no cover - unused
        return None


@pytest.mark.asyncio
async def test_sync_worker_processes_jobs_with_async_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Jobs are executed using the async persistence wrappers."""

    reset_engine_for_tests()
    init_db()

    client = RecordingSoulseekClient()
    processed: List[Dict[str, Any]] = []
    processed_event = asyncio.Event()

    async def fake_process_job(self: SyncWorker, payload: Dict[str, Any]) -> None:
        processed.append(payload)
        processed_event.set()

    monkeypatch.setattr(SyncWorker, "_process_job", fake_process_job)

    worker = SyncWorker(client, concurrency=1)
    try:
        await worker.start()
        await asyncio.sleep(0)

        await worker.enqueue(
            {
                "username": "tester",
                "files": [{"download_id": 123, "priority": 1}],
                "priority": 1,
            }
        )

        await asyncio.wait_for(processed_event.wait(), timeout=1.0)
    finally:
        await worker.stop()

    assert len(processed) == 1
    assert processed[0]["username"] == "tester"


@pytest.mark.asyncio
async def test_sync_worker_persistence_calls_leave_event_loop_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queue interactions should yield to the event loop even under load."""

    reset_engine_for_tests()
    init_db()

    client = RecordingSoulseekClient()
    jobs = [
        {
            "username": "tester",
            "files": [],
            "priority": 1,
        }
        for _ in range(5)
    ]
    processed: List[Dict[str, Any]] = []

    async def slow_process_job(self: SyncWorker, payload: Dict[str, Any]) -> None:
        await asyncio.sleep(0.02)
        processed.append(payload)

    monkeypatch.setattr(SyncWorker, "_process_job", slow_process_job)

    async def delayed_enqueue(job_type: str, payload: Dict[str, Any], **kwargs: Any):
        await asyncio.sleep(0)
        return await enqueue_async(job_type, payload, **kwargs)

    async def delayed_fetch_ready(job_type: str):
        await asyncio.sleep(0)
        return await fetch_ready_async(job_type)

    async def delayed_lease(job_id: int, job_type: str, lease_seconds: int | None):
        await asyncio.sleep(0)
        return await lease_async(job_id, job_type=job_type, lease_seconds=lease_seconds)

    async def delayed_complete(
        job_id: int, job_type: str, result_payload: Dict[str, Any] | None
    ):
        await asyncio.sleep(0)
        return await complete_async(
            job_id, job_type=job_type, result_payload=result_payload
        )

    async def delayed_fail(
        job_id: int,
        job_type: str,
        error: str | None,
        retry_in: int | None,
        available_at: datetime | None,
        stop_reason: str | None,
    ):
        await asyncio.sleep(0)
        return await fail_async(
            job_id,
            job_type=job_type,
            error=error,
            retry_in=retry_in,
            available_at=available_at,
            stop_reason=stop_reason,
        )

    async def delayed_release(job_type: str):
        await asyncio.sleep(0)
        await release_active_leases_async(job_type)

    worker = SyncWorker(
        client,
        concurrency=1,
        base_poll_interval=0.01,
        idle_poll_interval=0.02,
        enqueue_fn=delayed_enqueue,
        fetch_ready_fn=delayed_fetch_ready,
        lease_fn=delayed_lease,
        complete_fn=delayed_complete,
        fail_fn=delayed_fail,
        release_active_leases_fn=delayed_release,
    )

    ticker_stop = asyncio.Event()
    ticker_count = 0

    async def ticker() -> None:
        nonlocal ticker_count
        while not ticker_stop.is_set():
            await asyncio.sleep(0)
            ticker_count += 1

    ticker_task = asyncio.create_task(ticker())
    ticks_during_enqueue = 0

    try:
        await worker.start()
        await asyncio.sleep(0)

        await asyncio.gather(*(worker.enqueue(job) for job in jobs))
        ticks_during_enqueue = ticker_count

        await asyncio.wait_for(worker.queue.join(), timeout=3.0)
        await asyncio.sleep(0.05)
    finally:
        ticker_stop.set()
        ticker_task.cancel()
        with suppress(asyncio.CancelledError):
            await ticker_task
        await worker.stop()

    assert (
        ticks_during_enqueue > 0
    ), "Event loop should make progress during persistence calls"
    assert client.status_calls > 0, "Poll loop should continue to run"
    assert len(processed) == len(jobs)
