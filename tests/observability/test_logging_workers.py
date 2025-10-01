from __future__ import annotations

from app.db import session_scope
from app.models import QueueJob
from app.workers import persistence


def _clear_queue() -> None:
    with session_scope() as session:
        session.query(QueueJob).delete()


def test_logging_worker_job_lifecycle_events(monkeypatch) -> None:
    _clear_queue()
    captured: list[tuple[str, dict]] = []

    def _capture(logger, event_name: str, /, **fields):
        captured.append((event_name, fields))

    monkeypatch.setattr("app.workers.persistence.log_event", _capture)

    job = persistence.enqueue("observability", {"foo": "bar"})
    persistence.fetch_ready("observability", limit=5)

    leased = persistence.lease(job.id, job_type="observability")
    assert leased is not None

    assert persistence.complete(job.id, job_type="observability", result_payload={"ok": True})
    assert persistence.to_dlq(
        job.id,
        job_type="observability",
        reason="max_retries_exhausted",
        payload={"reason": "tests"},
    )

    assert captured, "expected worker events to be emitted"

    def _find(event: str, status: str | None = None):
        matches = [payload for name, payload in captured if name == event]
        if status is not None:
            matches = [payload for payload in matches if payload.get("status") == status]
        return matches

    enqueued = _find("worker.job", "enqueued")
    assert enqueued and enqueued[-1]["entity_id"] == str(job.id)
    assert enqueued[-1]["job_type"] == "observability"

    leased_event = _find("worker.job", "leased")
    assert leased_event and leased_event[-1]["entity_id"] == str(job.id)
    assert leased_event[-1]["lease_timeout_s"] >= 5

    completed_event = _find("worker.job", "completed")
    assert completed_event and completed_event[-1]["entity_id"] == str(job.id)
    assert completed_event[-1]["has_result"] is True

    dead_letter_event = _find("worker.job", "dead_letter")
    assert dead_letter_event and dead_letter_event[-1]["stop_reason"] == "max_retries_exhausted"

    retry_events = _find("worker.retry_exhausted")
    assert retry_events and retry_events[-1]["entity_id"] == str(job.id)

    tick_events = _find("worker.tick", "ready")
    assert tick_events and tick_events[-1]["job_type"] == "observability"
    assert tick_events[-1]["count"] >= 0
