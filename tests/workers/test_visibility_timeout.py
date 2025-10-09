"""Tests for queue job visibility timeouts and redelivery."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.db import session_scope
from app.models import QueueJob, QueueJobStatus
from app.workers.persistence import enqueue, fetch_ready, lease


def test_visibility_timeout_redelivery() -> None:
    job = enqueue(
        "sync", {"idempotency_key": "job-1", "priority": 2, "visibility_timeout": 5}
    )

    leased = lease(job.id, job_type="sync", lease_seconds=5)
    assert leased is not None

    expired_at = datetime.utcnow() - timedelta(seconds=1)
    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        db_job.lease_expires_at = expired_at
        db_job.status = QueueJobStatus.LEASED.value
        session.add(db_job)

    pending = fetch_ready("sync")
    assert any(item.id == job.id for item in pending)

    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        assert db_job.status == QueueJobStatus.PENDING.value
        assert db_job.lease_expires_at is None
