"""Central definitions of activity event status constants."""

from __future__ import annotations

from typing import Final

AUTOSYNC_BLOCKED: Final = "autosync_blocked"
SYNC_BLOCKED: Final = "sync_blocked"
DOWNLOAD_BLOCKED: Final = "download_blocked"
DOWNLOAD_RETRY_SCHEDULED: Final = "download_retry_scheduled"
DOWNLOAD_RETRY_FAILED: Final = "download_retry_failed"
DOWNLOAD_RETRY_COMPLETED: Final = "download_retry_completed"
WORKER_STARTED: Final = "started"
WORKER_STOPPED: Final = "stopped"
WORKER_STALE: Final = "stale"
WORKER_RESTARTED: Final = "restarted"

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
