"""Structured logging helpers for orchestrator components."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.logging_events import log_event
from app.utils.settings_store import increment_counter


def format_datetime(value: datetime | None) -> str | None:
    """Return an ISO formatted timestamp for ``value`` if present."""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone(timezone.utc).isoformat()


def emit_schedule_event(
    logger: Any,
    *,
    job_id: int | str,
    job_type: str,
    attempts: int,
    priority: int,
    available_at: str | None,
) -> None:
    payload = {
        "entity_id": str(job_id),
        "job_type": job_type,
        "status": "ready",
        "attempts": attempts,
        "priority": priority,
    }
    if available_at is not None:
        payload["available_at"] = available_at
    _emit_event(logger, "orchestrator.schedule", payload)


def emit_lease_event(
    logger: Any,
    *,
    job_id: int | str,
    job_type: str,
    status: str,
    priority: int,
    lease_timeout: int,
) -> None:
    payload = {
        "entity_id": str(job_id),
        "job_type": job_type,
        "status": status,
        "priority": priority,
        "lease_timeout": lease_timeout,
    }
    _emit_event(logger, "orchestrator.lease", payload)


def emit_dispatch_event(
    logger: Any,
    *,
    job_id: int | str,
    job_type: str,
    status: str,
    attempts: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "entity_id": str(job_id),
        "job_type": job_type,
        "status": status,
    }
    if attempts is not None:
        payload["attempts"] = attempts
    _emit_event(logger, "orchestrator.dispatch", payload)


def emit_commit_event(
    logger: Any,
    *,
    job_id: int | str,
    job_type: str,
    status: str,
    attempts: int,
    duration_ms: int,
    retry_in: int | None = None,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "entity_id": str(job_id),
        "job_type": job_type,
        "status": status,
        "attempts": attempts,
        "duration_ms": duration_ms,
    }
    if retry_in is not None:
        payload["retry_in"] = retry_in
    if error:
        payload["error"] = error
    _emit_event(logger, "orchestrator.commit", payload, track_metric=True)


def emit_dlq_event(
    logger: Any,
    *,
    job_id: int | str,
    job_type: str,
    status: str,
    attempts: int | None = None,
    duration_ms: int | None = None,
    stop_reason: str | None = None,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "entity_id": str(job_id),
        "job_type": job_type,
        "status": status,
    }
    if attempts is not None:
        payload["attempts"] = attempts
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if stop_reason:
        payload["stop_reason"] = stop_reason
    if error:
        payload["error"] = error
    _emit_event(logger, "orchestrator.dlq", payload, track_metric=True)


def emit_heartbeat_event(
    logger: Any,
    *,
    job_id: int | str,
    job_type: str,
    status: str,
    lease_timeout: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "entity_id": str(job_id),
        "job_type": job_type,
        "status": status,
    }
    if lease_timeout is not None:
        payload["lease_timeout"] = lease_timeout
    _emit_event(logger, "orchestrator.heartbeat", payload)


def emit_timer_event(
    logger: Any,
    *,
    status: str,
    duration_ms: int,
    jobs_total: int,
    jobs_enqueued: int,
    jobs_failed: int,
    component: str | None = None,
    reason: str | None = None,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "status": status,
        "duration_ms": duration_ms,
        "jobs_total": jobs_total,
        "jobs_enqueued": jobs_enqueued,
        "jobs_failed": jobs_failed,
    }
    if component:
        payload["component"] = component
    if reason:
        payload["reason"] = reason
    if error:
        payload["error"] = error
    _emit_event(logger, "orchestrator.timer_tick", payload, track_metric=True)


def _emit_event(
    logger: Any,
    event: str,
    payload: dict[str, Any],
    *,
    track_metric: bool = False,
) -> None:
    log_event(logger, event, **payload)
    if track_metric:
        _increment_metric(event, payload.get("status"))


def _increment_metric(event: str, status: str | None) -> None:
    segments = ["metrics", *event.split(".")]
    if status:
        segments.append(status)
    else:
        segments.append("total")
    key = ".".join(segments)
    try:
        increment_counter(key)
    except Exception:  # pragma: no cover - defensive metrics hook
        pass


__all__ = [
    "emit_commit_event",
    "emit_dispatch_event",
    "emit_dlq_event",
    "emit_heartbeat_event",
    "emit_lease_event",
    "emit_schedule_event",
    "emit_timer_event",
    "format_datetime",
]

