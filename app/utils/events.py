"""Central definitions of activity event status constants."""

from __future__ import annotations

AUTOSYNC_BLOCKED = "autosync_blocked"
SYNC_BLOCKED = "sync_blocked"
DOWNLOAD_BLOCKED = "download_blocked"
DOWNLOAD_RETRY_SCHEDULED = "download_retry_scheduled"
DOWNLOAD_RETRY_FAILED = "download_retry_failed"
DOWNLOAD_RETRY_COMPLETED = "download_retry_completed"
WORKER_STARTED = "started"
WORKER_STOPPED = "stopped"
WORKER_STALE = "stale"
WORKER_RESTARTED = "restarted"

__all__ = [
    "AUTOSYNC_BLOCKED",
    "SYNC_BLOCKED",
    "DOWNLOAD_BLOCKED",
    "DOWNLOAD_RETRY_SCHEDULED",
    "DOWNLOAD_RETRY_FAILED",
    "DOWNLOAD_RETRY_COMPLETED",
    "WORKER_STARTED",
    "WORKER_STOPPED",
    "WORKER_STALE",
    "WORKER_RESTARTED",
]
