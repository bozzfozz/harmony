"""System status endpoints exposed for the dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from app.logging import get_logger

try:  # pragma: no cover - import guarded for environments without psutil
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - handled dynamically in endpoint
    psutil = None  # type: ignore


logger = get_logger(__name__)
router = APIRouter()

_START_TIME = datetime.now(timezone.utc)
_WORKER_LABELS = {
    "sync_worker": "soulseek_sync",
    "matching_worker": "matching",
    "scan_worker": "plex_scan",
    "playlist_worker": "playlist_sync",
}


def _worker_state(worker: Any) -> Dict[str, Any]:
    """Return a descriptive status payload for a background worker."""

    if worker is None:
        return {"state": "unavailable"}

    running: bool | None = None

    is_running = getattr(worker, "is_running", None)
    if callable(is_running):
        try:
            running = bool(is_running())
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to inspect worker status: %s", exc)
            running = None

    if running is None:
        flag = getattr(worker, "_running", None)
        if hasattr(flag, "is_set"):
            try:
                running = bool(flag.is_set())
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Failed to inspect worker flag: %s", exc)
        elif isinstance(flag, bool):
            running = flag

    queue_size = None
    queue = getattr(worker, "queue", None)
    if queue is not None and hasattr(queue, "qsize"):
        try:
            queue_size = int(queue.qsize())
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Unable to determine worker queue size: %s", exc)

    state = "running" if running else "idle"
    if running is None:
        state = "unknown"

    payload: Dict[str, Any] = {"state": state}
    if queue_size is not None:
        payload["queue_size"] = queue_size
    return payload


@router.get("/status", tags=["System"])
async def get_status(request: Request) -> Dict[str, Any]:
    """Return general application status data for the dashboard."""

    now = datetime.now(timezone.utc)
    uptime_seconds = (now - _START_TIME).total_seconds()
    workers = {
        label: _worker_state(getattr(request.app.state, attr, None))
        for attr, label in _WORKER_LABELS.items()
    }

    logger.debug("Reporting system status: uptime=%s seconds", uptime_seconds)
    return {
        "status": "ok",
        "version": getattr(request.app, "version", "unknown"),
        "uptime_seconds": round(uptime_seconds, 2),
        "workers": workers,
    }


@router.get("/api/system/stats", tags=["System"])
async def get_system_stats() -> Dict[str, Any]:
    """Return system statistics such as CPU, memory and disk usage."""

    if psutil is None:
        logger.error("psutil is not available; cannot provide system statistics")
        raise HTTPException(status_code=503, detail="System statistics unavailable")

    try:
        cpu_times = psutil.cpu_times_percent(interval=None, percpu=False)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to collect system statistics")
        raise HTTPException(status_code=500, detail="Failed to collect system statistics") from exc

    stats = {
        "cpu": {
            "percent": psutil.cpu_percent(interval=None),
            "cores": psutil.cpu_count(logical=True),
            "idle": getattr(cpu_times, "idle", 0.0),
            "user": getattr(cpu_times, "user", 0.0),
            "system": getattr(cpu_times, "system", 0.0),
        },
        "memory": {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent,
            "used": memory.used,
            "free": memory.free,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        },
        "network": {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        },
    }

    logger.debug("Collected system statistics: %s", stats)
    return stats

