"""Tests for retry and scheduling helpers in the queue persistence layer."""

from __future__ import annotations

from datetime import datetime

from app.db import session_scope
from app.models import QueueJob, QueueJobStatus
from app.workers.persistence import enqueue, fail, lease


def test_retry_failure_requeues_with_delay() -> None:
    job = enqueue("sync", {"idempotency_key": "retry-job", "priority": 1})

    leased = lease(job.id, job_type="sync", lease_seconds=5)
    assert leased is not None

    fail(job.id, job_type="sync", error="dependency timeout", retry_in=15)

    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        assert db_job.status == QueueJobStatus.PENDING.value
        assert db_job.last_error == "dependency timeout"
        assert db_job.lease_expires_at is None
        assert db_job.available_at is not None
        remaining = (db_job.available_at - datetime.utcnow()).total_seconds()
        assert remaining >= 14
