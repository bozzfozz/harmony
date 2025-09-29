"""Tests for worker job visibility timeouts and redelivery."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.db import session_scope
from app.models import WorkerJob
from app.workers.persistence import PersistentJobQueue


def test_visibility_timeout_redelivery() -> None:
    queue = PersistentJobQueue("sync")
    job = queue.enqueue({"idempotency_key": "job-1", "priority": 2, "visibility_timeout": 5})

    queue.mark_running(job.id, visibility_timeout=5)

    expired_at = datetime.utcnow() - timedelta(seconds=1)
    with session_scope() as session:
        db_job = session.get(WorkerJob, job.id)
        assert db_job is not None
        db_job.lease_expires_at = expired_at
        db_job.state = "running"
        session.add(db_job)

    pending = queue.list_pending()
    assert any(item.id == job.id for item in pending)

    with session_scope() as session:
        db_job = session.get(WorkerJob, job.id)
        assert db_job is not None
        assert db_job.state == "queued"
        assert db_job.lease_expires_at is None
