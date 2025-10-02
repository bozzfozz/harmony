"""Tests for orchestrator event helpers."""

from __future__ import annotations

import logging

from app.orchestrator import events


def test_increment_metric_logs_warning(monkeypatch, caplog):
    """Ensure metric increments that fail emit a structured warning."""

    def _raise_error(key: str) -> int:  # pragma: no cover - helper
        raise RuntimeError("boom")

    monkeypatch.setattr(events, "increment_counter", _raise_error)

    with caplog.at_level(logging.WARNING, logger="app.orchestrator.metrics"):
        events._increment_metric("orchestrator.commit", "failed")

    expected_key = "metrics.orchestrator.commit.failed"

    warning_record = next(
        (
            record
            for record in caplog.records
            if record.levelno == logging.WARNING
            and getattr(record, "event", "") == "orchestrator.metrics.increment_failed"
        ),
        None,
    )

    assert warning_record is not None
    assert warning_record.metric_key == expected_key
    assert warning_record.status == "error"
    assert warning_record.metric_status == "failed"
