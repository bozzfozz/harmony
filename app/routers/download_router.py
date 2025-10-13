"""Download management endpoints for Harmony."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response

from app.dependencies import get_download_service, get_hdm_orchestrator
from app.errors import ValidationAppError
from app.hdm.models import DownloadBatchRequest, DownloadRequestItem
from app.hdm.orchestrator import HdmOrchestrator
from app.logging import get_logger
from app.logging_events import log_event
from app.schemas import (
    DownloadEntryResponse,
    DownloadListResponse,
    DownloadPriorityUpdate,
    HdmBatchRequest,
    HdmSubmissionResponse,
    SoulseekDownloadRequest,
)
from app.services.download_service import DownloadService

router = APIRouter(tags=["Download"])
logger = get_logger("hdm.router")


def _parse_iso8601(value: str) -> datetime:
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:  # pragma: no cover - defensive validation
        raise ValidationAppError("Invalid datetime parameter") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


@router.get("/downloads", response_model=DownloadListResponse)
def list_downloads(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    all: bool = False,  # noqa: A002 - query parameter name mandated by API contract
    status_filter: str | None = Query(None, alias="status"),
    service: DownloadService = Depends(get_download_service),
) -> DownloadListResponse:
    """Return downloads with optional status filtering."""

    status_label = status_filter.strip() if status_filter else None
    log_event(
        logger,
        "api.download.list",
        component="router.download",
        status="requested",
        entity_id=None,
        include_all=all,
        status_filter=status_label,
        limit=limit,
        offset=offset,
    )
    downloads = service.list_downloads(
        include_all=all,
        status_filter=status_label,
        limit=limit,
        offset=offset,
    )
    return DownloadListResponse(downloads=downloads)


@router.post(
    "/downloads",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=HdmSubmissionResponse,
)
async def submit_hdm_batch(
    payload: HdmBatchRequest,
    orchestrator: HdmOrchestrator = Depends(get_hdm_orchestrator),
) -> HdmSubmissionResponse:
    """Submit a batch of Harmony Download Manager requests to the orchestrator."""

    items = [
        DownloadRequestItem(
            artist=item.artist.strip(),
            title=item.title.strip(),
            album=item.album.strip() if item.album else None,
            isrc=item.isrc.strip() if item.isrc else None,
            duration_seconds=item.duration_seconds,
            bitrate=item.bitrate,
            priority=item.priority if item.priority is not None else payload.priority,
            dedupe_key=item.dedupe_key,
            requested_by=(item.requested_by or payload.requested_by).strip(),
        )
        for item in payload.items
    ]
    batch_request = DownloadBatchRequest(
        items=items,
        requested_by=payload.requested_by,
        batch_id=payload.batch_id,
        priority=payload.priority,
        dedupe_key=payload.dedupe_key,
    )
    log_event(
        logger,
        "api.hdm.submit",
        component="router.hdm",
        status="requested",
        entity_id=batch_request.batch_id,
        items=len(batch_request.items),
        requested_by=batch_request.requested_by,
    )
    handle = await orchestrator.submit_batch(batch_request)
    return HdmSubmissionResponse(
        batch_id=handle.batch_id,
        items_total=handle.items_total,
        requested_by=handle.requested_by,
    )


@router.get("/download/{download_id}", response_model=DownloadEntryResponse)
def get_download(
    download_id: int,
    service: DownloadService = Depends(get_download_service),
) -> DownloadEntryResponse:
    """Return the persisted state of a single download."""

    log_event(
        logger,
        "api.download.detail",
        component="router.download",
        status="requested",
        entity_id=download_id,
    )
    download = service.get_download(download_id)
    return DownloadEntryResponse.model_validate(download)


@router.patch("/download/{download_id}/priority", response_model=DownloadEntryResponse)
def update_download_priority(
    download_id: int,
    payload: DownloadPriorityUpdate,
    service: DownloadService = Depends(get_download_service),
) -> DownloadEntryResponse:
    """Update the priority of a persisted download."""

    log_event(
        logger,
        "api.download.priority",
        component="router.download",
        status="requested",
        entity_id=download_id,
        priority=payload.priority,
    )
    download = service.update_priority(download_id, payload)
    return DownloadEntryResponse.model_validate(download)


@router.post("/download", status_code=status.HTTP_202_ACCEPTED)
async def start_download(
    payload: SoulseekDownloadRequest,
    request: Request,
    service: DownloadService = Depends(get_download_service),
) -> dict[str, Any]:
    """Persist requested downloads and enqueue them for the SyncWorker."""

    worker = getattr(request.app.state, "sync_worker", None)
    return await service.queue_downloads(payload, worker=worker)


@router.delete("/download/{download_id}")
async def cancel_download(
    download_id: int,
    service: DownloadService = Depends(get_download_service),
) -> dict[str, Any]:
    """Cancel a queued or running download."""

    log_event(
        logger,
        "api.download.cancel",
        component="router.download",
        status="requested",
        entity_id=download_id,
    )
    return await service.cancel_download(download_id)


@router.get("/downloads/export")
def export_downloads(
    format: str = Query("json"),
    status_filter: str | None = Query(None, alias="status"),
    from_time: str | None = Query(None, alias="from"),
    to_time: str | None = Query(None, alias="to"),
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
) -> dict[str, Any]:
    """Retry a failed or cancelled download by creating a new entry."""

    log_event(
        logger,
        "api.download.retry",
        component="router.download",
        status="requested",
        entity_id=download_id,
    )
    return await service.retry_download(download_id)
