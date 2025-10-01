from __future__ import annotations

from app.logging import get_logger
from app.orchestrator import events as orchestrator_events


def test_logging_orchestrator_events_on_dispatch_and_dlq(monkeypatch) -> None:
    logger = get_logger("tests.orchestrator")
    captured: list[tuple[str, dict]] = []

    def _capture(logger, event_name: str, /, **fields):
        captured.append((event_name, fields))

    monkeypatch.setattr("app.orchestrator.events.log_event", _capture)

    orchestrator_events.emit_dispatch_event(
        logger,
        job_id=42,
        job_type="sync",
        status="started",
        attempts=1,
    )
    orchestrator_events.emit_dlq_event(
        logger,
        job_id=42,
        job_type="sync",
        status="dead_letter",
        attempts=3,
        stop_reason="max_retries_exhausted",
        error="timeout",
    )

    dispatch_logs = [payload for name, payload in captured if name == "orchestrator.dispatch"]
    assert dispatch_logs and dispatch_logs[-1]["status"] == "started"
    assert dispatch_logs[-1]["entity_id"] == "42"
    assert dispatch_logs[-1]["job_type"] == "sync"

    dlq_logs = [payload for name, payload in captured if name == "orchestrator.dlq"]
    assert dlq_logs and dlq_logs[-1]["status"] == "dead_letter"
    assert dlq_logs[-1]["stop_reason"] == "max_retries_exhausted"
    assert dlq_logs[-1]["error"] == "timeout"
