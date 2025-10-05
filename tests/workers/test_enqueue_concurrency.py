"""Concurrency tests for queue persistence enqueue behaviour."""

from __future__ import annotations

import anyio
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import QueueJob
from app.workers.persistence import enqueue


@pytest.mark.anyio
async def test_enqueue_is_atomic_under_concurrency() -> None:
    payload_template = {"idempotency_key": "concurrent-job"}
    results: list[int] = []

    async def call(index: int) -> None:
        payload = dict(payload_template)
        payload["payload"] = {"value": index}
        job = await anyio.to_thread.run_sync(enqueue, "matching", payload)
        results.append(job.id)

    async with anyio.create_task_group() as tg:
        for idx in range(8):
            tg.start_soon(call, idx)

    assert len(results) == 8
    assert len(set(results)) == 1

    with session_scope() as session:
        stmt = select(func.count()).select_from(QueueJob).where(QueueJob.type == "matching")
        count = session.execute(stmt).scalar_one()
        assert count == 1

        record_stmt = select(QueueJob).where(QueueJob.type == "matching")
        record = session.execute(record_stmt).scalars().one()
        assert record.status == "pending"
        # The final payload should correspond to one of the attempted updates.
        assert record.payload["payload"]["value"] in range(8)


@pytest.mark.anyio
async def test_enqueue_returns_single_job_for_conflicting_requests() -> None:
    """Ensure the DTO returned from concurrent enqueues references the same record."""

    payload = {"idempotency_key": "conflict", "payload": {"value": 1}}
    ids: list[int] = []

    async def run() -> None:
        job = await anyio.to_thread.run_sync(enqueue, "metadata", payload)
        ids.append(job.id)

    async with anyio.create_task_group() as tg:
        for _ in range(2):
            tg.start_soon(run)

    assert len(ids) == 2
    assert len(set(ids)) == 1

    with session_scope() as session:
        stmt = select(func.count()).select_from(QueueJob).where(QueueJob.type == "metadata")
        count = session.execute(stmt).scalar_one()
        assert count == 1

        job_stmt = select(QueueJob.id).where(QueueJob.type == "metadata")
        job_id = session.execute(job_stmt).scalar_one()
        assert job_id is not None


@pytest.mark.anyio
async def test_enqueue_parallel_requests_return_existing_job() -> None:
    """Parallel enqueue calls should return the existing job without raising errors."""

    job_type = "parallel"
    template = {"idempotency_key": "parallel-job"}
    concurrency = 6
    barrier = threading.Barrier(concurrency)

    def run_parallel() -> list[int]:
        results: list[int] = []

        def worker(idx: int) -> int:
            payload = dict(template)
            payload["payload"] = {"attempt": idx}
            barrier.wait()
            job = enqueue(job_type, payload)
            return job.id

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            for job_id in executor.map(worker, range(concurrency)):
                results.append(job_id)

        return results

    results = await anyio.to_thread.run_sync(run_parallel)

    assert len(results) == concurrency
    assert len(set(results)) == 1

    with session_scope() as session:
        stmt = select(func.count()).select_from(QueueJob).where(QueueJob.type == job_type)
        count = session.execute(stmt).scalar_one()
        assert count == 1

        record_stmt = select(QueueJob).where(QueueJob.type == job_type)
        record = session.execute(record_stmt).scalars().one()
        assert record.payload["payload"]["attempt"] in range(concurrency)
