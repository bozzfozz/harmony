"""Tests for retry and scheduling helpers in the worker persistence layer."""

from __future__ import annotations

from datetime import datetime

from app.db import session_scope
from app.models import WorkerJob
from app.workers.persistence import PersistentJobQueue


def test_retry_failure_requeues_with_delay() -> None:
    queue = PersistentJobQueue("sync")
    job = queue.enqueue({"idempotency_key": "retry-job", "priority": 1})

    queue.mark_running(job.id, visibility_timeout=5)
    queue.mark_failed(
        job.id,
        "dependency timeout",
        redeliver=True,
        delay_seconds=15,
        stop_reason="dependency_error",
    )

    with session_scope() as session:
        db_job = session.get(WorkerJob, job.id)
        assert db_job is not None
        assert db_job.state == "queued"
        assert db_job.last_error == "dependency timeout"
        assert db_job.stop_reason == "dependency_error"
        assert db_job.scheduled_at is not None
        assert db_job.scheduled_at >= datetime.utcnow()
