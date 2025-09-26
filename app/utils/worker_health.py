"""Helper utilities for tracking worker heartbeat information."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.utils.settings_store import read_setting, write_setting

HEARTBEAT_PREFIX = "worker:"
STATUS_SUFFIX = ":status"
LAST_SEEN_SUFFIX = ":last_seen"
STALE_TIMEOUT_SECONDS = 60


def _utcnow_iso() -> str:
    """Return an ISO8601 timestamp in UTC."""

    return datetime.now(timezone.utc).isoformat()


def heartbeat_key(name: str) -> str:
    """Return the settings key storing the last heartbeat timestamp."""

    return f"{HEARTBEAT_PREFIX}{name}{LAST_SEEN_SUFFIX}"


def status_key(name: str) -> str:
    """Return the settings key storing the worker status."""

    return f"{HEARTBEAT_PREFIX}{name}{STATUS_SUFFIX}"


def record_worker_heartbeat(name: str, *, status: str = "running") -> str:
    """Persist a heartbeat and optional status for ``name``."""

    timestamp = _utcnow_iso()
    write_setting(heartbeat_key(name), timestamp)
    mark_worker_status(name, status)
    return timestamp


def mark_worker_status(name: str, status: str) -> None:
    """Persist the current status for ``name``."""

    write_setting(status_key(name), status)


def read_worker_status(name: str) -> tuple[Optional[str], Optional[str]]:
    """Return the stored ``(last_seen, status)`` tuple for ``name``."""

    return read_setting(heartbeat_key(name)), read_setting(status_key(name))


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO8601 timestamp if possible."""

    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def resolve_status(
    stored_status: Optional[str],
    last_seen: Optional[datetime],
    *,
    now: Optional[datetime] = None,
    stale_after: float = STALE_TIMEOUT_SECONDS,
) -> str:
    """Determine the effective worker status based on stored data."""

    status = (stored_status or "unknown").lower()
    if status == "stopped":
        return "stopped"

    reference = now or datetime.now(timezone.utc)
    if last_seen is not None and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)

    if last_seen is None:
        return status

    if (reference - last_seen).total_seconds() > stale_after and status != "stopped":
        return "stale"

    return status or "unknown"


__all__ = [
    "HEARTBEAT_PREFIX",
    "LAST_SEEN_SUFFIX",
    "STALE_TIMEOUT_SECONDS",
    "heartbeat_key",
    "status_key",
    "record_worker_heartbeat",
    "mark_worker_status",
    "read_worker_status",
    "parse_timestamp",
    "resolve_status",
]
