"""System status endpoints exposed for the dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from app.logging import get_logger
from app.db import session_scope
from app.models import Download, WorkerJob
from app.utils.activity import record_worker_stale
from app.utils.events import WORKER_STALE
from app.utils.service_health import evaluate_all_service_health
from app.utils.worker_health import (
    STALE_TIMEOUT_SECONDS,
    mark_worker_status,
    parse_timestamp,
    read_worker_status,
    resolve_status,
)
from sqlalchemy import func, select

try:  # pragma: no cover - import guarded for environments without psutil
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - handled dynamically in endpoint
    psutil = None  # type: ignore


logger = get_logger(__name__)
router = APIRouter()

_START_TIME = datetime.now(timezone.utc)
QueueValue = Any


@dataclass(frozen=True)
class WorkerDescriptor:
    attr: str
    queue_fetcher: Optional[Callable[[Request], QueueValue]] = None
    queue_literal: Optional[QueueValue] = None


def _sync_queue_size(_: Request) -> int:
    with session_scope() as session:
        result = session.execute(
            select(func.count())
            .select_from(Download)
            .where(Download.state.in_(["queued", "downloading"]))
        )
        count = result.scalar_one_or_none()
    return int(count or 0)


def _matching_queue_size(_: Request) -> int:
    with session_scope() as session:
        result = session.execute(
            select(func.count())
            .select_from(WorkerJob)
            .where(
                WorkerJob.worker == "matching",
                WorkerJob.state.in_(["queued", "running"]),
            )
        )
        count = result.scalar_one_or_none()
    return int(count or 0)


def _autosync_queue_status(request: Request) -> Dict[str, int]:
    worker = getattr(request.app.state, "auto_sync_worker", None)
    running = bool(getattr(worker, "_running", False))
    in_progress = bool(getattr(worker, "_in_progress", False))
    return {
        "scheduled": 1 if running else 0,
        "running": 1 if in_progress else 0,
    }


_WORKERS: Dict[str, WorkerDescriptor] = {
    "sync": WorkerDescriptor(attr="sync_worker", queue_fetcher=_sync_queue_size),
    "matching": WorkerDescriptor(attr="matching_worker", queue_fetcher=_matching_queue_size),
    "scan": WorkerDescriptor(attr="scan_worker", queue_literal="n/a"),
    "playlist": WorkerDescriptor(attr="playlist_worker", queue_literal="n/a"),
    "autosync": WorkerDescriptor(attr="auto_sync_worker", queue_fetcher=_autosync_queue_status),
}


def _worker_payload(name: str, descriptor: WorkerDescriptor, request: Request) -> Dict[str, Any]:
    stored_last_seen, stored_status = read_worker_status(name)
    last_seen_dt = parse_timestamp(stored_last_seen)
    now = datetime.now(timezone.utc)
    status = resolve_status(stored_status, last_seen_dt, now=now)
    stored_status_normalized = (stored_status or "").lower() if stored_status else ""

    if status == WORKER_STALE and stored_status_normalized != WORKER_STALE:
        elapsed: Optional[float] = None
        if last_seen_dt is not None:
            elapsed = (now - last_seen_dt).total_seconds()
        record_worker_stale(
            name,
            last_seen=stored_last_seen,
            threshold_seconds=STALE_TIMEOUT_SECONDS,
            elapsed_seconds=elapsed,
            timestamp=now.replace(tzinfo=None),
        )
        mark_worker_status(name, WORKER_STALE)

    payload: Dict[str, Any] = {"status": status}
    payload["last_seen"] = stored_last_seen

    queue_value: QueueValue | None = None
    if descriptor.queue_fetcher is not None:
        try:
            queue_value = descriptor.queue_fetcher(request)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Failed to obtain queue size for worker %s: %s", name, exc)
    elif descriptor.queue_literal is not None:
        queue_value = descriptor.queue_literal

    if queue_value is not None:
        payload["queue_size"] = queue_value

    worker_instance = getattr(request.app.state, descriptor.attr, None)
    if worker_instance is None and stored_last_seen is None:
        payload["status"] = "unavailable"

    return payload


@router.get("/status", tags=["System"])
async def get_status(request: Request) -> Dict[str, Any]:
    """Return general application status data for the dashboard."""

    now = datetime.now(timezone.utc)
    uptime_seconds = (now - _START_TIME).total_seconds()
    workers = {
        name: _worker_payload(name, descriptor, request)
        for name, descriptor in _WORKERS.items()
    }

    with session_scope() as session:
        service_health = evaluate_all_service_health(session)
        connections = {name: result.status for name, result in service_health.items()}

    logger.debug("Reporting system status: uptime=%s seconds", uptime_seconds)
    return {
        "status": "ok",
        "version": getattr(request.app, "version", "unknown"),
        "uptime_seconds": round(uptime_seconds, 2),
        "workers": workers,
        "connections": connections,
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

