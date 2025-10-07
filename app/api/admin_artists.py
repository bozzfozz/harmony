"""Administrative endpoints for managing artist synchronisation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.config import AppConfig, settings
from app.dependencies import get_app_config
from app.logging import get_logger
from app.logging_events import log_event
from app.orchestrator.handlers_artist import (
    ArtistSyncHandlerDeps,
    QueueJobDTO,
    _build_artist_dto,
    _build_release_dtos,
    _extract_aliases,
    _resolve_providers,
    _resolve_release_limit,
    _select_artist,
    _split_artist_key,
    enqueue_artist_sync,
    handle_artist_sync,
)
from app.orchestrator.providers import build_artist_sync_handler_deps
from app.services.artist_dao import ArtistDao
from app.services.artist_delta import (
    ArtistLocalState,
    ArtistRemoteState,
    ReleaseSnapshot,
    determine_delta,
    summarise_delta,
)
from app.services.audit import list_audit_events
from app.services.cache import ResponseCache, bust_artist_cache
from app.models import QueueJob, QueueJobStatus
from app.db import session_scope


router = APIRouter(prefix="/artists", tags=["Admin Artists"])
logger = get_logger(__name__)

_ADMIN_STATE_ATTR = "admin_artists_registered"
_ADMIN_ROUTES_ATTR = "admin_artists_routes"
_JOB_TYPE = "artist_sync"
_PRIORITY_BOOST = 10


@dataclass(slots=True)
class AdminContext:
    config: AppConfig
    deps: ArtistSyncHandlerDeps
    cache: ResponseCache | None


@dataclass(slots=True)
class QueueState:
    attempts: int
    active_job_id: int | None
    active_lease_expires_at: datetime | None


class SafetyReport(BaseModel):
    locked: bool
    retry_attempts: int = Field(0, alias="retryAttempts")
    retry_budget: int | None = Field(None, alias="retryBudget")
    stale: bool
    staleness_minutes: float | None = Field(None, alias="stalenessMinutes")
    active_job_id: int | None = Field(None, alias="activeJobId")
    active_lease_expires_at: datetime | None = Field(None, alias="activeLeaseExpiresAt")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "locked": False,
                "retryAttempts": 2,
                "retryBudget": 6,
                "stale": False,
                "stalenessMinutes": 12.5,
                "activeJobId": None,
                "activeLeaseExpiresAt": None,
            }
        },
    }


class ReleaseSummaryModel(BaseModel):
    title: str
    source: str | None = None
    source_id: str | None = Field(None, alias="sourceId")
    release_date: str | None = Field(None, alias="releaseDate")
    release_type: str | None = Field(None, alias="releaseType")

    model_config = {"populate_by_name": True}


class DeltaReleasesOut(BaseModel):
    added: list[ReleaseSummaryModel] = Field(default_factory=list)
    updated: list[ReleaseSummaryModel] = Field(default_factory=list)
    removed: list[ReleaseSummaryModel] = Field(default_factory=list)


class DeltaAliasesOut(BaseModel):
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class DeltaSummaryOut(BaseModel):
    added: int
    updated: int
    removed: int
    alias_added: int = Field(alias="aliasAdded")
    alias_removed: int = Field(alias="aliasRemoved")

    model_config = {"populate_by_name": True}


class ReconcileDeltaOut(BaseModel):
    summary: DeltaSummaryOut
    releases: DeltaReleasesOut
    aliases: DeltaAliasesOut


class ReconcileResponse(BaseModel):
    artist_key: str = Field(alias="artistKey")
    dry_run: bool = Field(alias="dryRun")
    applied: bool
    providers: list[str]
    provider_errors: dict[str, str] = Field(default_factory=dict, alias="providerErrors")
    delta: ReconcileDeltaOut
    safety: SafetyReport
    warnings: list[str] = Field(default_factory=list)
    result: Mapping[str, Any] | None = None

    model_config = {"populate_by_name": True}


class ResyncResponse(BaseModel):
    enqueued: bool
    job_id: int = Field(alias="jobId")
    priority: int

    model_config = {"populate_by_name": True}


class AuditEventOut(BaseModel):
    id: int
    created_at: datetime = Field(alias="createdAt")
    job_id: str | None = Field(alias="jobId", default=None)
    entity_type: str = Field(alias="entityType")
    entity_id: str | None = Field(alias="entityId", default=None)
    event: str
    before: Mapping[str, Any] | None = None
    after: Mapping[str, Any] | None = None

    model_config = {"populate_by_name": True}


class AuditPageOut(BaseModel):
    artist_key: str = Field(alias="artistKey")
    items: list[AuditEventOut]
    next_cursor: int | None = Field(alias="nextCursor", default=None)
    limit: int

    model_config = {"populate_by_name": True}


class InvalidateResponse(BaseModel):
    artist_key: str = Field(alias="artistKey")
    evicted: int

    model_config = {"populate_by_name": True}


def maybe_register_admin_routes(app: FastAPI, *, config: AppConfig | None = None) -> bool:
    """Include or remove the admin router based on feature flag state."""

    resolved_config = config or get_app_config()
    admin_enabled = bool(
        getattr(resolved_config, "admin", None) and resolved_config.admin.api_enabled
    )
    registered = bool(getattr(app.state, _ADMIN_STATE_ATTR, False))
    if not admin_enabled:
        if registered:
            _unregister_admin_routes(app)
        return False

    if registered:
        return True

    prefix = _resolve_admin_prefix(resolved_config)
    before = len(app.router.routes)
    app.include_router(router, prefix=prefix)
    added = tuple(app.router.routes[before:])
    setattr(app.state, _ADMIN_ROUTES_ATTR, added)
    setattr(app.state, _ADMIN_STATE_ATTR, True)
    return True


def _unregister_admin_routes(app: FastAPI) -> None:
    routes: tuple[Any, ...] = getattr(app.state, _ADMIN_ROUTES_ATTR, ())
    if not routes:
        setattr(app.state, _ADMIN_STATE_ATTR, False)
        return

    current_routes = list(app.router.routes)
    for route in routes:
        if route in current_routes:
            current_routes.remove(route)
    app.router.routes = current_routes  # type: ignore[attr-defined]
    setattr(app.state, _ADMIN_ROUTES_ATTR, tuple())
    setattr(app.state, _ADMIN_STATE_ATTR, False)


def _resolve_admin_prefix(config: AppConfig) -> str:
    _ = config
    return "/admin"


def _get_response_cache(request: Request) -> ResponseCache | None:
    cache = getattr(request.app.state, "response_cache", None)
    return cache if isinstance(cache, ResponseCache) else None


def _require_enabled(config: AppConfig) -> None:
    admin_config = getattr(config, "admin", None)
    if not admin_config or not admin_config.api_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def _error(
    status_code: int, code: str, message: str, *, meta: Mapping[str, Any] | None = None
) -> None:
    detail: dict[str, Any] = {"message": message, "code": code}
    if meta:
        detail["meta"] = dict(meta)
    raise HTTPException(status_code=status_code, detail=detail)


def _build_context(request: Request) -> AdminContext:
    config = get_app_config()
    _require_enabled(config)
    cache = _get_response_cache(request)
    deps = build_artist_sync_handler_deps(response_cache=cache)
    return AdminContext(config=config, deps=deps, cache=cache)


async def _load_local_state(
    dao: ArtistDao, artist_key: str
) -> tuple[ArtistLocalState, Any, Sequence[ReleaseSnapshot]]:
    def _load() -> tuple[Any, Sequence[ReleaseSnapshot]]:
        artist_row = dao.get_artist(artist_key)
        release_rows = dao.get_artist_releases(artist_key, include_inactive=True)
        snapshots = tuple(ReleaseSnapshot.from_row(row) for row in release_rows)
        return artist_row, snapshots

    artist_row, snapshots = await asyncio.to_thread(_load)
    aliases = _extract_aliases(artist_row.metadata if artist_row else None)
    return ArtistLocalState(releases=snapshots, aliases=aliases), artist_row, snapshots


async def _fetch_remote_state(
    deps: ArtistSyncHandlerDeps,
    artist_key: str,
) -> tuple[ArtistRemoteState, list[str], dict[str, str]]:
    source, source_id = _split_artist_key(artist_key)
    payload = {"artist_key": artist_key}
    providers = _resolve_providers(payload, default=deps.providers, fallback_source=source)
    release_limit = _resolve_release_limit(payload, deps.release_limit)
    lookup_identifier = source_id or artist_key

    response = await deps.gateway.fetch_artist(
        lookup_identifier,
        providers=providers,
        limit=release_limit,
    )
    artist = _select_artist(response, source)
    artist_name = str(payload.get("artist_name") or artist_key)
    artist_dto = _build_artist_dto(
        artist_key,
        artist,
        fallback_source=source,
        fallback_id=source_id,
        fallback_name=artist_name,
    )
    releases = _build_release_dtos(artist_key, response.releases)
    remote_aliases = _extract_aliases(artist_dto.metadata)
    remote_state = ArtistRemoteState(releases=tuple(releases), aliases=remote_aliases)

    errors = {
        result.provider: result.error.__class__.__name__
        for result in response.results
        if result.error is not None
    }
    return remote_state, list(providers), errors


def _queue_state(artist_key: str) -> QueueState:
    key = (artist_key or "").strip()
    attempts = 0
    active_id: int | None = None
    active_expires: datetime | None = None
    now = datetime.utcnow()

    with session_scope() as session:
        records = (
            session.query(QueueJob)
            .filter(
                QueueJob.type == _JOB_TYPE,
                QueueJob.status.in_([QueueJobStatus.PENDING.value, QueueJobStatus.LEASED.value]),
            )
            .all()
        )

    for record in records:
        payload = dict(record.payload or {})
        if (payload.get("artist_key") or "").strip() != key:
            continue
        attempts = max(attempts, int(record.attempts or 0))
        if (
            record.status == QueueJobStatus.LEASED.value
            and record.lease_expires_at
            and record.lease_expires_at > now
        ):
            active_id = int(record.id)
            active_expires = record.lease_expires_at

    return QueueState(
        attempts=attempts, active_job_id=active_id, active_lease_expires_at=active_expires
    )


async def _compute_staleness(
    artist_row: Any,
    releases: Sequence[ReleaseSnapshot],
    *,
    threshold_minutes: int,
) -> tuple[bool, float | None]:
    timestamps: list[datetime] = []
    if artist_row is not None and getattr(artist_row, "updated_at", None) is not None:
        timestamps.append(artist_row.updated_at)
    for snapshot in releases:
        if snapshot.updated_at is not None:
            timestamps.append(snapshot.updated_at)
    if not timestamps:
        return False, None
    latest = max(timestamp.replace(tzinfo=None) for timestamp in timestamps)
    now = datetime.utcnow()
    delta_minutes = (now - latest).total_seconds() / 60.0
    return delta_minutes > threshold_minutes, delta_minutes


def _build_delta_payload(delta: Any) -> ReconcileDeltaOut:
    summary = summarise_delta(delta)
    releases = DeltaReleasesOut(
        added=[ReleaseSummaryModel(**item.to_dict()) for item in summary.added],
        updated=[ReleaseSummaryModel(**item.to_dict()) for item in summary.updated],
        removed=[ReleaseSummaryModel(**item.to_dict()) for item in summary.removed],
    )
    aliases = DeltaAliasesOut(
        added=list(summary.alias_added),
        removed=list(summary.alias_removed),
    )
    summary_out = DeltaSummaryOut(
        added=summary.added_count,
        updated=summary.updated_count,
        removed=summary.removed_count,
        aliasAdded=summary.alias_added_count,
        aliasRemoved=summary.alias_removed_count,
    )
    return ReconcileDeltaOut(summary=summary_out, releases=releases, aliases=aliases)


async def _safety_report(
    context: AdminContext,
    artist_key: str,
    *,
    artist_row: Any,
    releases: Sequence[ReleaseSnapshot],
) -> SafetyReport:
    queue_state = await asyncio.to_thread(_queue_state, artist_key)
    stale, age = await _compute_staleness(
        artist_row,
        releases,
        threshold_minutes=context.config.admin.staleness_max_minutes,
    )
    retry_budget = context.config.admin.retry_budget_max or None
    return SafetyReport(
        locked=queue_state.active_job_id is not None,
        retryAttempts=queue_state.attempts,
        retryBudget=retry_budget,
        stale=stale,
        stalenessMinutes=age,
        activeJobId=queue_state.active_job_id,
        activeLeaseExpiresAt=queue_state.active_lease_expires_at,
    )


async def _run_sync_job(context: AdminContext, artist_key: str) -> Mapping[str, Any]:
    priority_base = settings.orchestrator.priority_map.get("sync", 0)
    priority = priority_base + _PRIORITY_BOOST
    payload = {
        "artist_key": artist_key,
        "force": True,
        "force_resync": True,
        "priority_override": priority,
    }
    job = QueueJobDTO(
        id=0,
        type=_JOB_TYPE,
        payload=payload,
        priority=priority,
        attempts=0,
        available_at=datetime.utcnow(),
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key=None,
    )
    return await handle_artist_sync(job, context.deps)


def _log_reconcile_event(
    *,
    artist_key: str,
    providers: Sequence[str],
    provider_errors: Mapping[str, str],
    delta: ReconcileDeltaOut,
    safety: SafetyReport,
    dry_run: bool,
    status: str,
    event: str,
    warnings: Sequence[str] | None = None,
    result: Mapping[str, Any] | None = None,
) -> None:
    meta: dict[str, Any] = {
        "delta_counts": delta.summary.model_dump(by_alias=True),
        "safety": safety.model_dump(by_alias=True),
    }
    if provider_errors:
        meta["provider_errors"] = dict(provider_errors)
    if warnings:
        meta["warnings"] = list(warnings)
    if result:
        meta["result"] = dict(result)

    log_event(
        logger,
        event,
        component="api.admin.artists",
        status=status,
        artist_key=artist_key,
        dry_run=dry_run,
        providers=",".join(providers),
        provider_error_count=len(provider_errors),
        meta=meta,
    )


@router.post("/{artist_key}/reconcile", response_model=ReconcileResponse)
async def reconcile_artist(
    artist_key: str,
    dry_run: bool = Query(True, alias="dry_run"),
    context: AdminContext = Depends(_build_context),
) -> ReconcileResponse:
    key = artist_key.strip()
    if not key:
        _error(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "artist_key must be provided")

    try:
        local_state, artist_row, release_snapshots = await _load_local_state(context.deps.dao, key)
        remote_state, providers, provider_errors = await _fetch_remote_state(context.deps, key)
        delta = determine_delta(local_state, remote_state)
        delta_payload = _build_delta_payload(delta)
        safety = await _safety_report(
            context,
            key,
            artist_row=artist_row,
            releases=release_snapshots,
        )

        warnings: list[str] = []
        if safety.stale:
            warnings.append(
                "Existing data appears stale; consider refreshing provider sources before applying."
            )
        if provider_errors:
            warnings.append("One or more providers returned errors during reconciliation.")

        if not dry_run:
            if safety.locked:
                _error(
                    status.HTTP_409_CONFLICT,
                    "RESOURCE_LOCKED",
                    "Artist is currently being processed.",
                    meta={"job_id": safety.active_job_id},
                )
            retry_budget = context.config.admin.retry_budget_max
            if retry_budget and safety.retry_attempts >= retry_budget:
                _error(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "RATE_LIMITED",
                    "Retry budget exhausted for this artist.",
                    meta={"attempts": safety.retry_attempts, "budget": retry_budget},
                )
            result = await _run_sync_job(context, key)
            _log_reconcile_event(
                artist_key=key,
                providers=providers,
                provider_errors=provider_errors,
                delta=delta_payload,
                safety=safety,
                dry_run=False,
                status="applied",
                event="artist.admin.reconcile",
                warnings=warnings,
                result=result,
            )
            return ReconcileResponse(
                artistKey=key,
                dryRun=False,
                applied=True,
                providers=providers,
                providerErrors=provider_errors,
                delta=delta_payload,
                safety=safety,
                warnings=warnings,
                result=result,
            )

        _log_reconcile_event(
            artist_key=key,
            providers=providers,
            provider_errors=provider_errors,
            delta=delta_payload,
            safety=safety,
            dry_run=True,
            status="ok",
            event="artist.admin.dry_run",
            warnings=warnings,
            result=None,
        )
        return ReconcileResponse(
            artistKey=key,
            dryRun=True,
            applied=False,
            providers=providers,
            providerErrors=provider_errors,
            delta=delta_payload,
            safety=safety,
            warnings=warnings,
            result=None,
        )
    except HTTPException:
        raise
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Admin reconcile failed", extra={"artist_key": key})
        raise


@router.post("/{artist_key}/resync", response_model=ResyncResponse)
async def trigger_resync(
    artist_key: str,
    context: AdminContext = Depends(_build_context),
) -> ResyncResponse:
    key = artist_key.strip()
    if not key:
        _error(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "artist_key must be provided")

    queue_state = await asyncio.to_thread(_queue_state, key)
    if queue_state.active_job_id is not None:
        _error(
            status.HTTP_409_CONFLICT,
            "RESOURCE_LOCKED",
            "Artist is currently being processed.",
            meta={"job_id": queue_state.active_job_id},
        )
    retry_budget = context.config.admin.retry_budget_max
    if retry_budget and queue_state.attempts >= retry_budget:
        _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "RATE_LIMITED",
            "Retry budget exhausted for this artist.",
            meta={"attempts": queue_state.attempts, "budget": retry_budget},
        )

    priority_base = settings.orchestrator.priority_map.get("sync", 0)
    priority = priority_base + _PRIORITY_BOOST
    job = await enqueue_artist_sync(
        key,
        force_resync=True,
        priority=priority,
    )
    log_event(
        logger,
        "artist.admin.resync",
        component="api.admin.artists",
        status="enqueued",
        artist_key=key,
        job_id=job.id,
        priority=priority,
    )
    return ResyncResponse(enqueued=True, jobId=int(job.id), priority=priority)


@router.get("/{artist_key}/audit", response_model=AuditPageOut)
async def list_audit(
    artist_key: str,
    limit: int = Query(100, ge=1, le=200),
    cursor: int | None = Query(None),
    context: AdminContext = Depends(_build_context),
) -> AuditPageOut:
    key = artist_key.strip()
    if not key:
        _error(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "artist_key must be provided")

    rows, next_cursor = list_audit_events(key, limit=limit, cursor=cursor)
    events = [
        AuditEventOut(
            id=row.id,
            createdAt=row.created_at,
            jobId=row.job_id,
            entityType=row.entity_type,
            entityId=row.entity_id,
            event=row.event,
            before=row.before,
            after=row.after,
        )
        for row in rows
    ]
    log_event(
        logger,
        "artist.admin.audit",
        component="api.admin.artists",
        status="ok",
        artist_key=key,
        count=len(events),
    )
    return AuditPageOut(
        artistKey=key,
        items=events,
        nextCursor=next_cursor,
        limit=limit,
    )


@router.post("/{artist_key}/invalidate", response_model=InvalidateResponse)
async def invalidate_artist_cache(
    artist_key: str,
    context: AdminContext = Depends(_build_context),
) -> InvalidateResponse:
    key = artist_key.strip()
    if not key:
        _error(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "artist_key must be provided")

    cache = context.cache
    evicted = await bust_artist_cache(
        cache,
        artist_key=key,
        base_path=context.config.api_base_path,
        reason="admin_invalidate",
        entity_id=key,
    )
    log_event(
        logger,
        "artist.admin.invalidate",
        component="api.admin.artists",
        status="ok",
        artist_key=key,
        evicted=evicted,
    )
    return InvalidateResponse(artistKey=key, evicted=evicted)


__all__ = ["maybe_register_admin_routes", "router"]
