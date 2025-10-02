"""Download management endpoints for Harmony."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response

from app.dependencies import get_download_service
from app.logging import get_logger
from app.schemas import (
    DownloadEntryResponse,
    DownloadListResponse,
    DownloadPriorityUpdate,
    SoulseekDownloadRequest,
)
from app.services.download_service import DownloadService
from app.errors import ValidationAppError

router = APIRouter(tags=["Download"])
logger = get_logger(__name__)


def _parse_iso8601(value: str) -> datetime:
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:  # pragma: no cover - defensive validation
        raise ValidationAppError("Invalid datetime parameter") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


@router.get("/downloads", response_model=DownloadListResponse)
def list_downloads(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    all: bool = False,  # noqa: A002 - query parameter name mandated by API contract
    status_filter: Optional[str] = Query(None, alias="status"),
    service: DownloadService = Depends(get_download_service),
) -> DownloadListResponse:
    """Return downloads with optional status filtering."""

    status_label = status_filter.strip() if status_filter else None
    logger.info(
        "Download list requested (all=%s, status=%s, limit=%s, offset=%s)",
        all,
        status_label,
        limit,
        offset,
    )
    downloads = service.list_downloads(
        include_all=all,
        status_filter=status_label,
        limit=limit,
        offset=offset,
    )
    return DownloadListResponse(downloads=downloads)


@router.get("/download/{download_id}", response_model=DownloadEntryResponse)
def get_download(
    download_id: int,
    service: DownloadService = Depends(get_download_service),
) -> DownloadEntryResponse:
    """Return the persisted state of a single download."""

    logger.info("Download detail requested for id=%s", download_id)
    download = service.get_download(download_id)
    return DownloadEntryResponse.model_validate(download)


@router.patch("/download/{download_id}/priority", response_model=DownloadEntryResponse)
def update_download_priority(
    download_id: int,
    payload: DownloadPriorityUpdate,
    service: DownloadService = Depends(get_download_service),
) -> DownloadEntryResponse:
    """Update the priority of a persisted download."""

    logger.info("Priority update requested for download %s", download_id)
    download = service.update_priority(download_id, payload)
    return DownloadEntryResponse.model_validate(download)


@router.post("/download", status_code=status.HTTP_202_ACCEPTED)
async def start_download(
    payload: SoulseekDownloadRequest,
    request: Request,
    service: DownloadService = Depends(get_download_service),
) -> Dict[str, Any]:
    """Persist requested downloads and enqueue them for the SyncWorker."""

    worker = getattr(request.app.state, "sync_worker", None)
    return await service.queue_downloads(payload, worker=worker)


@router.delete("/download/{download_id}")
async def cancel_download(
    download_id: int,
    service: DownloadService = Depends(get_download_service),
) -> Dict[str, Any]:
    """Cancel a queued or running download."""

    logger.info("Cancellation requested for download id=%s", download_id)
    return await service.cancel_download(download_id)


@router.get("/downloads/export")
def export_downloads(
    format: str = Query("json"),
    status_filter: Optional[str] = Query(None, alias="status"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
    service: DownloadService = Depends(get_download_service),
) -> Response:
    """Export downloads as JSON or CSV without paging limits."""

    fmt = (format or "json").strip().lower()
    if fmt not in {"json", "csv"}:
        raise ValidationAppError("Unsupported export format")

    status_label = status_filter.strip() if isinstance(status_filter, str) else None
    created_from = _parse_iso8601(from_time) if from_time else None
    created_to = _parse_iso8601(to_time) if to_time else None

    export = service.export_downloads(
        status_filter=status_label,
        created_from=created_from,
        created_to=created_to,
        format=fmt,
    )

    if fmt == "json":
        return Response(
            content=json.dumps(export["content"], ensure_ascii=False),
            media_type=export["media_type"],
        )

    return Response(content=export["content"], media_type=export["media_type"])


@router.post("/download/{download_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_download(
    download_id: int,
    service: DownloadService = Depends(get_download_service),
) -> Dict[str, Any]:
    """Retry a failed or cancelled download by creating a new entry."""

    logger.info("Retry requested for download id=%s", download_id)
    return await service.retry_download(download_id)
