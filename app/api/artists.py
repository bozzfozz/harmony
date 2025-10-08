"""Public API endpoints for artist metadata and watchlist management."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response, status

from app.dependencies import get_artist_service
from app.errors import AppError, InternalServerError
from app.logging import get_logger
from app.logging_events import log_event
from app.schemas.artists import (ArtistOut, EnqueueResponse,
                                 EnqueueSyncRequest, ReleaseOut,
                                 WatchlistItemIn, WatchlistItemOut,
                                 WatchlistPageOut)
from app.services.artist_service import (ArtistDetails, ArtistService,
                                         WatchlistPage)

router = APIRouter(prefix="/artists", tags=["Artists"])
_logger = get_logger(__name__)


def _emit_api_event(
    request: Request,
    *,
    component: str,
    status_code: int,
    status: str,
    duration_ms: float,
    error: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "component": component,
        "status": status,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 3),
        "entity_id": getattr(request.state, "request_id", None),
    }
    if error is not None:
        payload["error"] = error
    if meta:
        payload["meta"] = meta
    log_event(_logger, "api.request", **payload)


def _to_artist_response(details: ArtistDetails) -> ArtistOut:
    artist = ArtistOut.model_validate(details.artist)
    artist.releases = [ReleaseOut.model_validate(release) for release in details.releases]
    return artist


def _to_watchlist_page(page: WatchlistPage) -> WatchlistPageOut:
    items = [WatchlistItemOut.model_validate(entry) for entry in page.items]
    return WatchlistPageOut(items=items, total=page.total, limit=page.limit, offset=page.offset)


@router.get("/watchlist", response_model=WatchlistPageOut)
def list_watchlist(
    request: Request,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: ArtistService = Depends(get_artist_service),
) -> WatchlistPageOut:
    started = perf_counter()
    try:
        page = service.list_watchlist(limit=limit, offset=offset)
    except AppError as exc:
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            component="api.artists.watchlist",
            status_code=exc.http_status,
            status="error",
            duration_ms=duration_ms,
            error=exc.code,
            meta={"limit": limit, "offset": offset},
        )
        raise
    except Exception as exc:  # pragma: no cover - safety net
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            component="api.artists.watchlist",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            duration_ms=duration_ms,
            error="unexpected_error",
            meta={"limit": limit, "offset": offset},
        )
        raise InternalServerError("Failed to load watchlist.") from exc

    duration_ms = (perf_counter() - started) * 1000
    meta = {"limit": page.limit, "offset": page.offset, "total": page.total}
    _emit_api_event(
        request,
        component="api.artists.watchlist",
        status_code=status.HTTP_200_OK,
        status="ok",
        duration_ms=duration_ms,
        meta=meta,
    )
    return _to_watchlist_page(page)


@router.post(
    "/watchlist",
    response_model=WatchlistItemOut,
    status_code=status.HTTP_201_CREATED,
)
def upsert_watchlist(
    payload: WatchlistItemIn,
    request: Request,
    service: ArtistService = Depends(get_artist_service),
) -> WatchlistItemOut:
    started = perf_counter()
    try:
        entry = service.upsert_watchlist(
            artist_key=payload.artist_key,
            priority=payload.priority,
            cooldown_until=payload.cooldown_until,
        )
    except AppError as exc:
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            component="api.artists.watchlist",
            status_code=exc.http_status,
            status="error",
            duration_ms=duration_ms,
            error=exc.code,
            meta={"artist_key": payload.artist_key},
        )
        raise
    except Exception as exc:  # pragma: no cover - safety net
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            component="api.artists.watchlist",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            duration_ms=duration_ms,
            error="unexpected_error",
            meta={"artist_key": payload.artist_key},
        )
        raise InternalServerError("Failed to update watchlist.") from exc

    duration_ms = (perf_counter() - started) * 1000
    _emit_api_event(
        request,
        component="api.artists.watchlist",
        status_code=status.HTTP_201_CREATED,
        status="ok",
        duration_ms=duration_ms,
        meta={"artist_key": entry.artist_key, "priority": entry.priority},
    )
    return WatchlistItemOut.model_validate(entry)


@router.delete("/watchlist/{artist_key}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watchlist(
    artist_key: str,
    request: Request,
    service: ArtistService = Depends(get_artist_service),
) -> Response:
    started = perf_counter()
    try:
        service.remove_watchlist(artist_key)
    except AppError as exc:
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            component="api.artists.watchlist",
            status_code=exc.http_status,
            status="error",
            duration_ms=duration_ms,
            error=exc.code,
            meta={"artist_key": artist_key},
        )
        raise
    except Exception as exc:  # pragma: no cover - safety net
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            component="api.artists.watchlist",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            duration_ms=duration_ms,
            error="unexpected_error",
            meta={"artist_key": artist_key},
        )
        raise InternalServerError("Failed to remove watchlist entry.") from exc

    duration_ms = (perf_counter() - started) * 1000
    _emit_api_event(
        request,
        component="api.artists.watchlist",
        status_code=status.HTTP_204_NO_CONTENT,
        status="ok",
        duration_ms=duration_ms,
        meta={"artist_key": artist_key},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{artist_key}", response_model=ArtistOut)
def get_artist(
    artist_key: str,
    request: Request,
    service: ArtistService = Depends(get_artist_service),
) -> ArtistOut:
    started = perf_counter()
    try:
        details = service.get_artist(artist_key)
    except AppError as exc:
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            component="api.artists",
            status_code=exc.http_status,
            status="error",
            duration_ms=duration_ms,
            error=exc.code,
            meta={"artist_key": artist_key},
        )
        raise
    except Exception as exc:  # pragma: no cover - safety net
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            component="api.artists",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            duration_ms=duration_ms,
            error="unexpected_error",
            meta={"artist_key": artist_key},
        )
        raise InternalServerError("Failed to load artist.") from exc

    duration_ms = (perf_counter() - started) * 1000
    meta = {
        "artist_key": details.artist.artist_key,
        "release_count": len(details.releases),
    }
    _emit_api_event(
        request,
        component="api.artists",
        status_code=status.HTTP_200_OK,
        status="ok",
        duration_ms=duration_ms,
        meta=meta,
    )
    return _to_artist_response(details)


@router.post(
    "/{artist_key}/enqueue-sync",
    response_model=EnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_artist_sync_endpoint(
    artist_key: str,
    request: Request,
    payload: EnqueueSyncRequest | None = Body(default=None),
    service: ArtistService = Depends(get_artist_service),
) -> EnqueueResponse:
    started = perf_counter()
    try:
        force = bool(payload.force) if payload is not None else False
        result = await service.enqueue_sync(artist_key, force=force)
    except AppError as exc:
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            component="api.artists",
            status_code=exc.http_status,
            status="error",
            duration_ms=duration_ms,
            error=exc.code,
            meta={"artist_key": artist_key},
        )
        raise
    except Exception as exc:  # pragma: no cover - safety net
        duration_ms = (perf_counter() - started) * 1000
        _emit_api_event(
            request,
            component="api.artists",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            status="error",
            duration_ms=duration_ms,
            error="unexpected_error",
            meta={"artist_key": artist_key},
        )
        raise InternalServerError("Failed to enqueue artist sync.") from exc

    job = result.job
    response = EnqueueResponse(
        job_id=int(job.id),
        job_type=str(job.type),
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        priority=int(job.priority or 0),
        available_at=job.available_at,
        already_enqueued=result.already_enqueued,
    )

    duration_ms = (perf_counter() - started) * 1000
    meta = {
        "artist_key": artist_key,
        "already_enqueued": result.already_enqueued,
        "job_id": int(job.id),
    }
    _emit_api_event(
        request,
        component="api.artists",
        status_code=status.HTTP_202_ACCEPTED,
        status="ok",
        duration_ms=duration_ms,
        meta=meta,
    )
    return response


__all__ = ["router"]
