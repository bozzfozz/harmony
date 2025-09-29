"""Tests for job idempotency behaviour in the worker persistence queue."""

from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models import WorkerJob
from app.workers.persistence import PersistentJobQueue


def test_idempotent_processing_prevents_duplicates() -> None:
    queue = PersistentJobQueue("matching")
    payload = {"idempotency_key": "match-123", "payload": {"value": 42}}

    first = queue.enqueue(payload)
    second = queue.enqueue(payload)

    assert first.id == second.id

    with session_scope() as session:
        stmt = select(WorkerJob).where(
            WorkerJob.worker == "matching", WorkerJob.job_key == first.job_key
        )
        jobs = session.execute(stmt).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].payload["payload"]["value"] == 42
