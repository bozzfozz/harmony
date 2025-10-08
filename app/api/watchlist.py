"""Watchlist API exposing CRUD endpoints backed by the in-memory service."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status

from app.dependencies import get_watchlist_service
from app.errors import AppError, InternalServerError
from app.logging import get_logger
from app.logging_events import log_event
from app.schemas.watchlist import (
    WatchlistEntryCreate,
    WatchlistEntryResponse,
    WatchlistListResponse,
    WatchlistPauseRequest,
    WatchlistPriorityUpdate,
)
from app.services.watchlist_service import WatchlistService

router = APIRouter(prefix="/watchlist", tags=["Watchlist"])
_logger = get_logger(__name__)


def _emit_api_event(
    request: Request,
    *,
    status_code: int,
    status: str,
    duration_ms: float,
    error: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "component": "api.watchlist",
        "status": status,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 3),
        "entity_id": getattr(request.state, "request_id", None),
    }
    if error:
        payload["error"] = error
    if meta:
        payload["meta"] = meta
    log_event(_logger, "api.request", **payload)


def _to_response(entry: Any) -> WatchlistEntryResponse:
    return WatchlistEntryResponse.model_validate(entry)


@router.get("", response_model=WatchlistListResponse)
def list_watchlist(
    request: Request,
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistListResponse:
    started = perf_counter()
    try:
        entries = service.list_entries()
    except Exception as exc:  # pragma: no cover - defensive guard
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            duration_ms=duration_ms,
            error="unexpected_error",
        )
        raise InternalServerError("Failed to load watchlist entries.") from exc

    duration_ms = (perf_counter() - started) * 1000
    payload = WatchlistListResponse(items=[_to_response(entry) for entry in entries])
    _emit_api_event(
        request,
        status_code=status.HTTP_200_OK,
        status="ok",
        duration_ms=duration_ms,
        meta={"count": len(payload.items)},
    )
    return payload


@router.post("", response_model=WatchlistEntryResponse, status_code=status.HTTP_201_CREATED)
def create_watchlist_entry(
    payload: WatchlistEntryCreate,
    request: Request,
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistEntryResponse:
    started = perf_counter()
    try:
        entry = service.create_entry(artist_key=payload.artist_key, priority=payload.priority)
    except AppError as exc:
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            status_code=exc.http_status,
            status="error",
            duration_ms=duration_ms,
            error=exc.code,
            meta={"artist_key": payload.artist_key},
        )
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            duration_ms=duration_ms,
            error="unexpected_error",
            meta={"artist_key": payload.artist_key},
        )
        raise InternalServerError("Failed to create watchlist entry.") from exc

    duration_ms = (perf_counter() - started) * 1000
    _emit_api_event(
        request,
        status_code=status.HTTP_201_CREATED,
        status="ok",
        duration_ms=duration_ms,
        meta={"artist_key": entry.artist_key, "priority": entry.priority},
    )
    return _to_response(entry)


@router.patch("/{artist_key}", response_model=WatchlistEntryResponse)
def update_watchlist_priority(
    artist_key: str,
    payload: WatchlistPriorityUpdate,
    request: Request,
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistEntryResponse:
    started = perf_counter()
    try:
        entry = service.update_priority(artist_key=artist_key, priority=payload.priority)
    except AppError as exc:
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            status_code=exc.http_status,
            status="error",
            duration_ms=duration_ms,
            error=exc.code,
            meta={"artist_key": artist_key},
        )
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            duration_ms=duration_ms,
            error="unexpected_error",
            meta={"artist_key": artist_key},
        )
        raise InternalServerError("Failed to update watchlist priority.") from exc

    duration_ms = (perf_counter() - started) * 1000
    _emit_api_event(
        request,
        status_code=status.HTTP_200_OK,
        status="ok",
        duration_ms=duration_ms,
        meta={"artist_key": entry.artist_key, "priority": entry.priority},
    )
    return _to_response(entry)


@router.post("/{artist_key}/pause", response_model=WatchlistEntryResponse)
def pause_watchlist_entry(
    artist_key: str,
    payload: WatchlistPauseRequest,
    request: Request,
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistEntryResponse:
    started = perf_counter()
    try:
        entry = service.pause_entry(
            artist_key=artist_key,
            reason=payload.reason,
            resume_at=payload.resume_at,
        )
    except AppError as exc:
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            status_code=exc.http_status,
            status="error",
            duration_ms=duration_ms,
            error=exc.code,
            meta={"artist_key": artist_key},
        )
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            duration_ms=duration_ms,
            error="unexpected_error",
            meta={"artist_key": artist_key},
        )
        raise InternalServerError("Failed to pause watchlist entry.") from exc

    duration_ms = (perf_counter() - started) * 1000
    meta: dict[str, Any] = {"artist_key": entry.artist_key, "paused": entry.paused}
    if entry.pause_reason:
        meta["reason"] = entry.pause_reason
    if entry.resume_at:
        meta["resume_at"] = entry.resume_at.isoformat()
    _emit_api_event(
        request,
        status_code=status.HTTP_200_OK,
        status="ok",
        duration_ms=duration_ms,
        meta=meta,
    )
    return _to_response(entry)


@router.post("/{artist_key}/resume", response_model=WatchlistEntryResponse)
def resume_watchlist_entry(
    artist_key: str,
    request: Request,
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistEntryResponse:
    started = perf_counter()
    try:
        entry = service.resume_entry(artist_key=artist_key)
    except AppError as exc:
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            status_code=exc.http_status,
            status="error",
            duration_ms=duration_ms,
            error=exc.code,
            meta={"artist_key": artist_key},
        )
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            duration_ms=duration_ms,
            error="unexpected_error",
            meta={"artist_key": artist_key},
        )
        raise InternalServerError("Failed to resume watchlist entry.") from exc

    duration_ms = (perf_counter() - started) * 1000
    _emit_api_event(
        request,
        status_code=status.HTTP_200_OK,
        status="ok",
        duration_ms=duration_ms,
        meta={"artist_key": entry.artist_key, "paused": entry.paused},
    )
    return _to_response(entry)


@router.delete("/{artist_key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist_entry(
    artist_key: str,
    request: Request,
    service: WatchlistService = Depends(get_watchlist_service),
) -> Response:
    started = perf_counter()
    try:
        service.remove_entry(artist_key=artist_key)
    except AppError as exc:
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            status_code=exc.http_status,
            status="error",
            duration_ms=duration_ms,
            error=exc.code,
            meta={"artist_key": artist_key},
        )
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            duration_ms=duration_ms,
            error="unexpected_error",
            meta={"artist_key": artist_key},
        )
        raise InternalServerError("Failed to delete watchlist entry.") from exc

    duration_ms = (perf_counter() - started) * 1000
    _emit_api_event(
        request,
        status_code=status.HTTP_204_NO_CONTENT,
        status="ok",
        duration_ms=duration_ms,
        meta={"artist_key": artist_key},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
