"""System status endpoints exposed for the dashboard."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import inspect
import sys
import time
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.dependencies import get_db
from app.errors import DependencyError
from app.logging import get_logger
from app.models import Download, QueueJob, QueueJobStatus
from app.services.health import HealthService
from app.services.secret_store import SecretStore
from app.services.secret_validation import (
    SecretValidationResult,
    SecretValidationService,
    SecretValidationSettings,
)
from app.utils import metrics
from app.utils.activity import record_worker_stale
from app.utils.events import WORKER_STALE
from app.utils.service_health import evaluate_all_service_health
from app.utils.worker_health import (
    STALE_TIMEOUT_SECONDS,
    mark_worker_status,
    orchestrator_component_status,
    orchestrator_job_status,
    parse_timestamp,
    read_worker_status,
    resolve_status,
)
from app.ops.selfcheck import aggregate_ready

try:  # pragma: no cover - import guarded for environments without psutil
    import psutil as _psutil  # type: ignore
except ImportError:  # pragma: no cover - handled dynamically in endpoint
    _psutil = None  # type: ignore

psutil = _psutil  # type: ignore


logger = get_logger(__name__)
router = APIRouter()

_START_TIME = datetime.now(UTC)
QueueValue = Any


class SecretValidationRequest(BaseModel):
    value: str | None = Field(
        default=None,
        description="Optional override secret value used only for validation.",
        max_length=256,
    )


class SecretValidatedPayload(BaseModel):
    mode: Literal["live", "format"]
    valid: bool
    at: datetime
    reason: str | None = None
    note: str | None = None


class SecretValidationPayload(BaseModel):
    provider: str
    validated: SecretValidatedPayload


class SecretValidationEnvelope(BaseModel):
    ok: bool
    data: SecretValidationPayload
    error: dict[str, Any] | None = None


_DEFAULT_SECRET_VALIDATION_SERVICE = SecretValidationService(
    settings=SecretValidationSettings.from_env()
)


def _get_health_service(request: Request) -> HealthService:
    service = getattr(request.app.state, "health_service", None)
    if service is None:  # pragma: no cover - configuration guard
        raise RuntimeError("Health service is not configured")
    return cast(HealthService, service)


def _get_secret_validation_service(request: Request) -> SecretValidationService:
    service = getattr(request.app.state, "secret_validation_service", None)
    if service is None:
        return _DEFAULT_SECRET_VALIDATION_SERVICE
    return cast(SecretValidationService, service)


@router.get("/health", tags=["System"])
async def get_health(request: Request) -> dict[str, Any]:
    """Return liveness information without external I/O."""

    service = _get_health_service(request)
    start = time.perf_counter()
    summary = service.liveness()
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "Reporting liveness status",  # pragma: no cover - logging string
        extra={
            "event": "health.check",
            "status": summary.status,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return {
        "ok": True,
        "data": {
            "status": summary.status,
            "version": summary.version,
            "uptime_s": summary.uptime_s,
        },
        "error": None,
    }


@router.get("/ready", tags=["System"])
async def get_readiness(request: Request) -> dict[str, Any]:
    """Check database connectivity and configured dependencies."""

    service = _get_health_service(request)
    start = time.perf_counter()
    result = await service.readiness()
    duration_ms = (time.perf_counter() - start) * 1000
    deps = result.dependencies
    orchestrator_components: dict[str, str] = {}
    orchestrator_jobs: dict[str, str] = {}
    filtered_deps: dict[str, str] = {}
    for name, status_text in deps.items():
        if name.startswith("orchestrator:job:"):
            _, _, job_name = name.partition(":job:")
            orchestrator_jobs[job_name or name] = status_text
        elif name.startswith("orchestrator:"):
            _, _, component = name.partition(":")
            orchestrator_components[component or name] = status_text
        else:
            filtered_deps[name] = status_text
    orchestrator_status = getattr(request.app.state, "orchestrator_status", {})
    orchestrator_enabled_jobs = dict(orchestrator_status.get("enabled_jobs", {}))
    healthy_statuses = {"up", "enabled", "disabled", "not_required"}
    deps_up = sum(1 for status in deps.values() if status in healthy_statuses)
    deps_down = sum(1 for status in deps.values() if status not in healthy_statuses)
    logger.info(
        "Reporting readiness status",  # pragma: no cover - logging string
        extra={
            "event": "ready.check",
            "db": result.database,
            "deps_up": deps_up,
            "deps_down": deps_down,
            "duration_ms": round(duration_ms, 2),
        },
    )
    readiness_payload = {
        "db": result.database,
        "deps": filtered_deps,
        "orchestrator": {
            "components": orchestrator_components,
            "jobs": orchestrator_jobs,
            "enabled_jobs": orchestrator_enabled_jobs,
        },
    }

    if result.ok:
        return {"ok": True, "data": readiness_payload, "error": None}

    error = DependencyError(
        "not ready",
        meta={
            "db": result.database,
            "deps": deps,
            "orchestrator": readiness_payload["orchestrator"],
        },
    )
    response = error.as_response(request_path=request.url.path, method=request.method)
    return response


@router.get("/metrics", tags=["System"])
async def get_metrics() -> Response:
    """Expose Prometheus metrics collected by the Harmony backend."""

    registry = metrics.get_registry()
    payload = generate_latest(registry)
    headers = {"Cache-Control": "no-store"}
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST, headers=headers)


@router.post(
    "/secrets/{provider}/validate",
    response_model=SecretValidationEnvelope,
    tags=["System"],
    include_in_schema=False,
)
async def validate_secret(
    provider: str,
    request: Request,
    payload: SecretValidationRequest | None = None,
    session: Session = Depends(get_db),
) -> SecretValidationEnvelope:
    service = _get_secret_validation_service(request)
    store = SecretStore(session)
    normalized_provider = provider.strip().lower()
    override_value = payload.value if payload is not None else None
    result: SecretValidationResult = await service.validate(
        normalized_provider,
        store=store,
        override=override_value,
    )
    response_payload = SecretValidationPayload(
        provider=result.provider,
        validated=SecretValidatedPayload(**result.validated.as_dict()),
    )
    return SecretValidationEnvelope(ok=True, data=response_payload, error=None)


@dataclass(frozen=True)
class WorkerDescriptor:
    attr: str | None
    queue_fetcher: Callable[[Request], QueueValue] | None = None
    queue_literal: QueueValue | None = None
    orchestrator_component: str | None = None
    orchestrator_job: str | None = None


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
            .select_from(QueueJob)
            .where(
                QueueJob.type == "matching",
                QueueJob.status.in_([QueueJobStatus.PENDING.value, QueueJobStatus.LEASED.value]),
            )
        )
        count = result.scalar_one_or_none()
    return int(count or 0)


_WORKERS: dict[str, WorkerDescriptor] = {
    "sync": WorkerDescriptor(attr="sync_worker", queue_fetcher=_sync_queue_size),
    "matching": WorkerDescriptor(attr="matching_worker", queue_fetcher=_matching_queue_size),
    "playlist": WorkerDescriptor(attr="playlist_worker", queue_literal="n/a"),
    "backfill": WorkerDescriptor(attr="backfill_worker", queue_literal="n/a"),
    "watchlist": WorkerDescriptor(attr="watchlist_worker", queue_literal="n/a"),
    "artwork": WorkerDescriptor(attr="artwork_worker", queue_literal="n/a"),
    "lyrics": WorkerDescriptor(attr="lyrics_worker", queue_literal="n/a"),
    "import": WorkerDescriptor(attr="import_worker", queue_literal="n/a"),
    "scheduler": WorkerDescriptor(
        attr=None, queue_literal="n/a", orchestrator_component="scheduler"
    ),
    "dispatcher": WorkerDescriptor(
        attr=None, queue_literal="n/a", orchestrator_component="dispatcher"
    ),
    "watchlist_timer": WorkerDescriptor(
        attr=None,
        queue_literal="n/a",
        orchestrator_component="watchlist_timer",
    ),
}


def _worker_payload(name: str, descriptor: WorkerDescriptor, request: Request) -> dict[str, Any]:
    stored_last_seen, stored_status = read_worker_status(name)
    last_seen_dt = parse_timestamp(stored_last_seen)
    now = datetime.now(UTC)
    status = resolve_status(stored_status, last_seen_dt, now=now)
    stored_status_normalized = (stored_status or "").lower() if stored_status else ""

    if status == WORKER_STALE and stored_status_normalized != WORKER_STALE:
        elapsed: float | None = None
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

    payload: dict[str, Any] = {"status": status}
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

    if descriptor.orchestrator_component:
        component_status = orchestrator_component_status(
            request.app, descriptor.orchestrator_component
        )
        payload["status"] = component_status
        payload["component"] = descriptor.orchestrator_component
    elif descriptor.orchestrator_job:
        job_status = orchestrator_job_status(request.app, descriptor.orchestrator_job)
        payload["status"] = job_status
        payload["job"] = descriptor.orchestrator_job

    worker_instance = None
    if descriptor.attr:
        worker_instance = getattr(request.app.state, descriptor.attr, None)
        if worker_instance is None and stored_last_seen is None:
            payload["status"] = "unavailable"

    return payload


@router.get("/status", tags=["System"])
async def get_status(request: Request) -> dict[str, Any]:
    """Return general application status data for the dashboard."""

    now = datetime.now(UTC)
    start_time = getattr(request.app.state, "start_time", _START_TIME)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=UTC)
    uptime_seconds = (now - start_time).total_seconds()
    workers = {
        name: _worker_payload(name, descriptor, request) for name, descriptor in _WORKERS.items()
    }

    with session_scope() as session:
        service_health = evaluate_all_service_health(session)
        connections = {name: result.status for name, result in service_health.items()}

    ready_report = aggregate_ready()
    overall_status = "ok" if ready_report.ok else "degraded"

    logger.debug(
        "Reporting system status: uptime=%s seconds",
        uptime_seconds,
        extra={"readiness_status": ready_report.status},
    )
    return {
        "status": overall_status,
        "version": getattr(request.app, "version", "unknown"),
        "uptime_seconds": round(uptime_seconds, 2),
        "workers": workers,
        "connections": connections,
        "readiness": ready_report.to_dict(verbose=True),
    }


def _call_dependency_override(override: Callable[..., Any], request: Request | None) -> Any:
    if request is None:
        return override()

    try:
        signature = inspect.signature(override)
    except (TypeError, ValueError):
        try:
            return override(request)
        except TypeError:
            return override()

    parameters = list(signature.parameters.values())
    if not parameters:
        return override()

    for parameter in parameters:
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            return override(request)

    request_parameter = signature.parameters.get("request")
    if request_parameter is not None and request_parameter.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    ):
        return override(request=request)

    return override()


def _resolve_psutil(request: Request | None = None):
    resolved = None
    if request is not None:
        overrides = getattr(request.app, "dependency_overrides", None)
        if isinstance(overrides, Mapping):
            override = overrides.get(_resolve_psutil)
            if override is not None:
                resolved = _call_dependency_override(override, request)
        if resolved is not None:
            return resolved

        state_psutil = getattr(request.app.state, "psutil", None)
        if state_psutil is not None:
            return state_psutil

    for shim_name in (
        "app.routers.system_router",
        "app.api.routers.system_router",
        "app.api.routers.system",
        "app.routers.system",
    ):
        shim = sys.modules.get(shim_name)
        if shim is None:
            continue
        candidate = getattr(shim, "psutil", None)
        if candidate is not None:
            return candidate

    return psutil


@router.get("/system/stats", tags=["System"])
async def get_system_stats(request: Request) -> dict[str, Any]:
    """Return system statistics such as CPU, memory and disk usage."""

    current_psutil = _resolve_psutil(request)
    if current_psutil is None:
        logger.error("psutil is not available; cannot provide system statistics")
        raise HTTPException(status_code=503, detail="System statistics unavailable")

    try:
        cpu_times = current_psutil.cpu_times_percent(interval=None, percpu=False)
        memory = current_psutil.virtual_memory()
        disk = current_psutil.disk_usage("/")
        net = current_psutil.net_io_counters()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to collect system statistics")
        raise HTTPException(status_code=500, detail="Failed to collect system statistics") from exc

    stats = {
        "cpu": {
            "percent": current_psutil.cpu_percent(interval=None),
            "cores": current_psutil.cpu_count(logical=True),
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
