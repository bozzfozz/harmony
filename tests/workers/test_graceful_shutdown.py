"""Tests covering graceful shutdown behaviour of worker queues."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.db import session_scope
from app.models import WorkerJob
from app.workers.persistence import PersistentJobQueue


def test_requeue_incomplete_respects_active_leases() -> None:
    queue = PersistentJobQueue("watchlist")
    active_job = queue.enqueue({"idempotency_key": "active"})
    expired_job = queue.enqueue({"idempotency_key": "expired"})

    queue.mark_running(active_job.id, visibility_timeout=30)
    queue.mark_running(expired_job.id, visibility_timeout=5)

    with session_scope() as session:
        exp = session.get(WorkerJob, expired_job.id)
        assert exp is not None
        exp.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        session.add(exp)

    queue.requeue_incomplete()

    with session_scope() as session:
        active = session.get(WorkerJob, active_job.id)
        expired = session.get(WorkerJob, expired_job.id)
        assert active is not None and active.state == "running"
        assert expired is not None and expired.state == "queued"
