"""Tests for job idempotency behaviour in the queue persistence layer."""

from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models import QueueJob
from app.workers.persistence import enqueue


def test_idempotent_processing_prevents_duplicates() -> None:
    payload = {"idempotency_key": "match-123", "payload": {"value": 42}}

    first = enqueue("matching", payload)
    second = enqueue("matching", payload)

    assert first.id == second.id

    with session_scope() as session:
        stmt = select(QueueJob).where(
            QueueJob.type == "matching", QueueJob.id == first.id
        )
        jobs = session.execute(stmt).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].payload["payload"]["value"] == 42
