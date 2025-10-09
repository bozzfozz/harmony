"""HTTP endpoints for managing the dead-letter queue."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.config import get_env
from app.dependencies import get_db
from app.errors import InternalServerError, ValidationAppError
from app.services.dlq_service import DLQListResult, DLQRequeueResult, DLQService, DLQStats

router = APIRouter(tags=["DLQ"])


def _env_int(name: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    raw = get_env(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
    if value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


_PAGE_SIZE_DEFAULT = _env_int("DLQ_PAGE_SIZE_DEFAULT", 25, minimum=1, maximum=100)
_PAGE_SIZE_MAX = _env_int("DLQ_PAGE_SIZE_MAX", 100, minimum=1, maximum=500)
_REQUEUE_LIMIT = _env_int("DLQ_REQUEUE_LIMIT", 500, minimum=1, maximum=1000)
_PURGE_LIMIT = _env_int("DLQ_PURGE_LIMIT", 1000, minimum=1, maximum=5000)


def _normalise_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_ids(raw_ids: list[str], *, limit: int) -> list[int]:
    if not raw_ids:
        raise ValidationAppError(f"ids required (1..{limit})")
    if len(raw_ids) > limit:
        raise ValidationAppError(f"ids exceed limit of {limit}")
    parsed: list[int] = []
    for candidate in raw_ids:
        text = candidate.strip()
        if not text:
            raise ValidationAppError("ids must not contain empty values")
        try:
            parsed_id = int(text)
        except ValueError as exc:
            raise ValidationAppError("ids must be integers") from exc
        parsed.append(parsed_id)
    return parsed


def _build_service(request: Request) -> DLQService:
    return DLQService(
        requeue_limit=_REQUEUE_LIMIT,
        purge_limit=_PURGE_LIMIT,
    )


def _resolve_actor(request: Request) -> str:
    presented = request.headers.get("X-API-Key") or request.headers.get("Authorization")
    if not presented:
        return "anonymous"
    digest = hashlib.blake2b(presented.encode("utf-8"), digest_size=8).hexdigest()
    return f"api:{digest}"


class DLQItemPayload(BaseModel):
    id: str
    entity: Literal["download"]
    reason: str
    message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    retry_count: int

    model_config = ConfigDict(from_attributes=True)


class DLQListData(BaseModel):
    items: list[DLQItemPayload]
    page: int
    page_size: int
    total: int


class DLQResponseEnvelope(BaseModel):
    ok: bool
    data: DLQListData
    error: Optional[Dict[str, Any]] = None


class DLQRequeueRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1)


class DLQSkippedEntry(BaseModel):
    id: str
    reason: str


class DLQRequeueData(BaseModel):
    requeued: list[str]
    skipped: list[DLQSkippedEntry]


class DLQRequeueEnvelope(BaseModel):
    ok: bool
    data: DLQRequeueData
    error: Optional[Dict[str, Any]] = None


class DLQPurgeRequest(BaseModel):
    ids: Optional[list[str]] = None
    older_than: Optional[datetime] = None
    reason: Optional[str] = None

    @model_validator(mode="after")
    def _validate_choice(self) -> "DLQPurgeRequest":
        if self.ids and self.older_than:
            raise ValueError("ids and older_than cannot be combined")
        if not self.ids and self.older_than is None:
            raise ValueError("Either ids or older_than must be provided")
        return self


class DLQPurgeData(BaseModel):
    purged: int


class DLQPurgeEnvelope(BaseModel):
    ok: bool
    data: DLQPurgeData
    error: Optional[Dict[str, Any]] = None


class DLQStatsData(BaseModel):
    total: int
    by_reason: Dict[str, int]
    last_24h: int


class DLQStatsEnvelope(BaseModel):
    ok: bool
    data: DLQStatsData
    error: Optional[Dict[str, Any]] = None


@router.get("", response_model=DLQResponseEnvelope)
def list_dlq(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(_PAGE_SIZE_DEFAULT, ge=1, le=_PAGE_SIZE_MAX),
    order_by: Literal["created_at", "updated_at"] = Query("created_at"),
    order_dir: Literal["asc", "desc"] = Query("desc"),
    reason: Optional[str] = Query(None),
    created_from: Optional[datetime] = Query(None, alias="from"),
    created_to: Optional[datetime] = Query(None, alias="to"),
    session: Session = Depends(get_db),
) -> DLQResponseEnvelope:
    service = _build_service(request)
    result: DLQListResult = service.list_entries(
        session,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
        reason=reason.strip() if reason else None,
        created_from=_normalise_datetime(created_from),
        created_to=_normalise_datetime(created_to),
    )
    items = [DLQItemPayload.model_validate(item) for item in result.items]
    data = DLQListData(
        items=items, page=result.page, page_size=result.page_size, total=result.total
    )
    return DLQResponseEnvelope(ok=True, data=data, error=None)


@router.post("/requeue", response_model=DLQRequeueEnvelope)
async def requeue_dlq(
    request: Request,
    payload: DLQRequeueRequest,
    session: Session = Depends(get_db),
) -> DLQRequeueEnvelope:
    service = _build_service(request)
    worker = getattr(request.app.state, "sync_worker", None)
    if worker is None or not hasattr(worker, "enqueue"):
        raise InternalServerError("Sync worker unavailable")

    ids = _parse_ids(payload.ids, limit=_REQUEUE_LIMIT)
    result: DLQRequeueResult = await service.requeue_bulk(
        session,
        ids=ids,
        worker=worker,
        actor=_resolve_actor(request),
    )
    skipped = [DLQSkippedEntry.model_validate(entry) for entry in result.skipped]
    data = DLQRequeueData(requeued=result.requeued, skipped=skipped)
    return DLQRequeueEnvelope(ok=True, data=data, error=None)


@router.post("/purge", response_model=DLQPurgeEnvelope)
def purge_dlq(
    request: Request,
    payload: DLQPurgeRequest,
    session: Session = Depends(get_db),
) -> DLQPurgeEnvelope:
    service = _build_service(request)
    ids = _parse_ids(payload.ids, limit=_PURGE_LIMIT) if payload.ids else None
    result = service.purge_bulk(
        session,
        ids=ids,
        older_than=_normalise_datetime(payload.older_than),
        reason=payload.reason.strip() if payload.reason else None,
        actor=_resolve_actor(request),
    )
    data = DLQPurgeData(purged=result.purged)
    return DLQPurgeEnvelope(ok=True, data=data, error=None)


@router.get("/stats", response_model=DLQStatsEnvelope)
def dlq_stats(
    request: Request,
    session: Session = Depends(get_db),
) -> DLQStatsEnvelope:
    service = _build_service(request)
    result: DLQStats = service.stats(session)
    data = DLQStatsData(total=result.total, by_reason=result.by_reason, last_24h=result.last_24h)
    return DLQStatsEnvelope(ok=True, data=data, error=None)


__all__ = ["router"]
