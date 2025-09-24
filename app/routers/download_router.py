"""Download management endpoints for Harmony."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, MutableMapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.transfers_api import TransfersApi, TransfersApiError
from app.dependencies import get_db, get_transfers_api
from app.logging import get_logger
from app.models import Download
from app.schemas import (
    DownloadEntryResponse,
    DownloadListResponse,
    DownloadPriorityUpdate,
    SoulseekDownloadRequest,
)
from app.utils.activity import record_activity
from app.workers.persistence import PersistentJobQueue

router = APIRouter(prefix="/api", tags=["Download"])
logger = get_logger(__name__)


STATUS_FILTERS: Dict[str, set[str]] = {
    "running": {"running", "downloading"},
    "queued": {"queued"},
    "completed": {"completed"},
    "failed": {"failed"},
    "cancelled": {"cancelled"},
}

ACTIVE_STATES = STATUS_FILTERS["running"] | STATUS_FILTERS["queued"]


def _normalise_status(value: str) -> str:
    return value.strip().lower()


def _resolve_status_filter(value: str) -> set[str]:
    normalised = _normalise_status(value)
    states = STATUS_FILTERS.get(normalised)
    if states is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid status filter",
        )
    return states


def _parse_iso8601(value: str) -> datetime:
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:  # pragma: no cover - defensive validation
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid datetime parameter",
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _build_download_query(
    session: Session,
    *,
    include_all: bool,
    status_filter: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
) -> Any:
    query = session.query(Download)
    if status_filter:
        states = _resolve_status_filter(status_filter)
        query = query.filter(Download.state.in_(tuple(states)))
    elif not include_all:
        query = query.filter(Download.state.in_(tuple(ACTIVE_STATES)))

    if created_from:
        query = query.filter(Download.created_at >= created_from)
    if created_to:
        query = query.filter(Download.created_at <= created_to)

    return query.order_by(Download.priority.desc(), Download.created_at.desc())


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalised = value.strip().lower()
        return normalised in {"1", "true", "yes", "y"}
    return False


def _determine_priority(file_info: MutableMapping[str, Any]) -> int:
    explicit = _coerce_int(file_info.get("priority"))
    if explicit is not None:
        return explicit

    favorite_keys = (
        "is_favorite",
        "favorite",
        "liked",
        "is_saved_track",
        "spotify_saved",
        "spotify_like",
    )
    if any(_is_truthy(file_info.get(key)) for key in favorite_keys):
        return 10

    source = str(file_info.get("source") or "").lower()
    if source in {"spotify_likes", "spotify_saved", "favorites"}:
        return 10

    return 0


def _serialise_download(download: Download) -> Dict[str, Any]:
    response = DownloadEntryResponse.model_validate(download).model_dump()
    response["username"] = download.username
    response["priority"] = download.priority
    created_at = download.created_at
    updated_at = download.updated_at
    response["created_at"] = created_at.isoformat() if created_at else None
    response["updated_at"] = updated_at.isoformat() if updated_at else None
    return response


CSV_HEADERS = [
    "id",
    "filename",
    "status",
    "progress",
    "username",
    "created_at",
    "updated_at",
]


@router.get("/downloads", response_model=DownloadListResponse)
def list_downloads(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    all: bool = False,  # noqa: A002 - query parameter name mandated by API contract
    status_filter: Optional[str] = Query(None, alias="status"),
    session: Session = Depends(get_db),
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
    try:
        query = _build_download_query(
            session,
            include_all=all,
            status_filter=status_label,
        )
        downloads = query.offset(offset).limit(limit).all()
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive database failure handling
        logger.exception("Failed to list downloads: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch downloads",
        ) from exc

    return DownloadListResponse(downloads=downloads)


@router.get("/download/{download_id}", response_model=DownloadEntryResponse)
def get_download(
    download_id: int,
    session: Session = Depends(get_db),
) -> DownloadEntryResponse:
    """Return the persisted state of a single download."""

    logger.info("Download detail requested for id=%s", download_id)
    try:
        download = session.get(Download, download_id)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive database failure handling
        logger.exception("Failed to load download %s: %s", download_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch download",
        ) from exc

    if download is None:
        logger.warning("Download %s not found", download_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Download not found")

    return DownloadEntryResponse.model_validate(download)


@router.patch("/download/{download_id}/priority", response_model=DownloadEntryResponse)
def update_download_priority(
    download_id: int,
    payload: DownloadPriorityUpdate,
    session: Session = Depends(get_db),
) -> DownloadEntryResponse:
    """Update the priority of a persisted download."""

    logger.info("Priority update requested for download %s", download_id)
    try:
        download = session.get(Download, download_id)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive database failure handling
        logger.exception("Failed to load download %s for priority update: %s", download_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update download priority",
        ) from exc

    if download is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Download not found")

    new_priority = int(payload.priority)
    download.priority = new_priority
    download.updated_at = datetime.utcnow()
    payload_copy = dict(download.request_payload or {})
    payload_copy["priority"] = new_priority
    download.request_payload = payload_copy
    session.add(download)
    session.commit()

    logger.info(
        "Updated priority for download %s to %s",
        download_id,
        new_priority,
    )

    job_id = download.job_id
    if job_id:
        queue = PersistentJobQueue("sync")
        if not queue.update_priority(job_id, new_priority):
            logger.error(
                "Failed to update worker job priority for download %s (job %s)",
                download_id,
                job_id,
            )

    return DownloadEntryResponse.model_validate(download)


@router.post("/download", status_code=status.HTTP_202_ACCEPTED)
async def start_download(
    payload: SoulseekDownloadRequest,
    request: Request,
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Persist requested downloads and enqueue them for the SyncWorker."""

    if not payload.files:
        logger.warning("Download request without files rejected")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files supplied")

    worker = getattr(request.app.state, "sync_worker", None)
    enqueue = getattr(worker, "enqueue", None)
    if enqueue is None:
        logger.error("Download worker unavailable for request from %s", payload.username)
        record_activity("download", "failed", details={"reason": "worker_unavailable"})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Download worker unavailable",
        )

    download_records: List[Download] = []
    job_files: List[Dict[str, Any]] = []
    try:
        job_priorities: List[int] = []
        for file_info in payload.files:
            filename = str(file_info.get("filename") or file_info.get("name") or "unknown")
            priority = _determine_priority(file_info)
            download = Download(
                filename=filename,
                state="queued",
                progress=0.0,
                username=payload.username,
                priority=priority,
            )
            session.add(download)
            session.flush()

            payload_copy = dict(file_info)
            payload_copy.setdefault("filename", filename)
            payload_copy["download_id"] = download.id
            payload_copy["priority"] = priority
            download.request_payload = payload_copy
            job_files.append(payload_copy)

            download_records.append(download)
            job_priorities.append(priority)
        session.commit()
    except Exception as exc:  # pragma: no cover - defensive persistence handling
        session.rollback()
        logger.exception("Failed to persist download request: %s", exc)
        record_activity("download", "failed", details={"reason": "persistence_error"})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to queue download") from exc

    job_priority = max(job_priorities or [0])
    job = {"username": payload.username, "files": job_files, "priority": job_priority}
    try:
        await enqueue(job)
    except Exception as exc:  # pragma: no cover - defensive worker error
        logger.exception("Failed to enqueue download job: %s", exc)
        now = datetime.utcnow()
        for download in download_records:
            download.state = "failed"
            download.updated_at = now
        session.commit()
        record_activity("download", "failed", details={"reason": "enqueue_error"})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to enqueue download") from exc

    download_payload = [
        {
            "id": download.id,
            "filename": download.filename,
            "state": download.state,
            "progress": download.progress,
            "priority": download.priority,
            "username": download.username,
        }
        for download in download_records
    ]

    record_activity(
        "download",
        "queued",
        details={
            "download_ids": [download.id for download in download_records],
            "username": payload.username,
        },
    )

    logger.info("Queued %d download(s) for %s", len(download_records), payload.username)

    primary_id = download_records[0].id if download_records else None
    response: Dict[str, Any] = {
        "status": "queued",
        "downloads": download_payload,
    }
    if primary_id is not None:
        response["download_id"] = primary_id
    return response


@router.delete("/download/{download_id}")
async def cancel_download(
    download_id: int,
    session: Session = Depends(get_db),
    transfers: TransfersApi = Depends(get_transfers_api),
) -> Dict[str, Any]:
    """Cancel a queued or running download."""

    logger.info("Cancellation requested for download id=%s", download_id)
    try:
        download = session.get(Download, download_id)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive database failure handling
        logger.exception("Failed to load download %s for cancellation: %s", download_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel download",
        ) from exc

    if download is None:
        logger.warning("Cancellation failed: download %s not found", download_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Download not found")

    if download.state not in {"queued", "running", "downloading"}:
        logger.warning(
            "Cancellation rejected for download %s due to invalid state %s",
            download_id,
            download.state,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Download cannot be cancelled in its current state",
        )

    try:
        await transfers.cancel_download(download_id)
    except TransfersApiError as exc:
        logger.error("slskd cancellation failed for %s: %s", download_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to cancel download via slskd",
        ) from exc

    download.state = "cancelled"
    download.updated_at = datetime.utcnow()

    try:
        session.commit()
    except Exception as exc:  # pragma: no cover - defensive persistence handling
        session.rollback()
        logger.exception("Failed to persist cancellation for download %s: %s", download_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel download",
        ) from exc

    record_activity(
        "download",
        "download_cancelled",
        details={"download_id": download_id, "filename": download.filename},
    )

    return {"status": "cancelled", "download_id": download_id}


@router.get("/downloads/export")
def export_downloads(
    format: str = Query("json"),
    status_filter: Optional[str] = Query(None, alias="status"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
    session: Session = Depends(get_db),
) -> Response:
    """Export downloads as JSON or CSV without paging limits."""

    fmt = (format or "json").strip().lower()
    if fmt not in {"json", "csv"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported export format",
        )

    status_label = status_filter.strip() if isinstance(status_filter, str) else None
    created_from = _parse_iso8601(from_time) if from_time else None
    created_to = _parse_iso8601(to_time) if to_time else None

    try:
        query = _build_download_query(
            session,
            include_all=True,
            status_filter=status_label,
            created_from=created_from,
            created_to=created_to,
        )
        downloads = query.all()
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive database failure handling
        logger.exception("Failed to export downloads: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export downloads",
        ) from exc

    payload = [_serialise_download(item) for item in downloads]

    if fmt == "json":
        return Response(
            content=json.dumps(payload, ensure_ascii=False),
            media_type="application/json",
        )

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_HEADERS)
    writer.writeheader()
    for item in payload:
        writer.writerow({
            "id": item.get("id"),
            "filename": item.get("filename"),
            "status": item.get("status"),
            "progress": item.get("progress"),
            "username": item.get("username"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        })

    return Response(content=buffer.getvalue(), media_type="text/csv")


@router.post("/download/{download_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_download(
    download_id: int,
    session: Session = Depends(get_db),
    transfers: TransfersApi = Depends(get_transfers_api),
) -> Dict[str, Any]:
    """Retry a failed or cancelled download by creating a new entry."""

    logger.info("Retry requested for download id=%s", download_id)
    try:
        original = session.get(Download, download_id)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive database failure handling
        logger.exception("Failed to load download %s for retry: %s", download_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retry download",
        ) from exc

    if original is None:
        logger.warning("Retry failed: download %s not found", download_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Download not found")

    if original.state not in {"failed", "cancelled"}:
        logger.warning(
            "Retry rejected for download %s due to invalid state %s",
            download_id,
            original.state,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Download cannot be retried in its current state",
        )

    if not original.username or not original.request_payload:
        logger.error("Retry rejected for download %s due to missing payload", download_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Download cannot be retried because original request data is missing",
        )

    payload_copy = dict(original.request_payload or {})
    filename = payload_copy.get("filename") or original.filename
    if not filename:
        logger.error("Retry rejected for download %s due to missing filename", download_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Download cannot be retried because filename is unknown",
        )

    filesize = (
        payload_copy.get("filesize")
        or payload_copy.get("size")
        or payload_copy.get("file_size")
    )
    if filesize is not None:
        payload_copy.setdefault("filesize", filesize)

    priority = _coerce_int(payload_copy.get("priority"))
    if priority is None:
        priority = original.priority

    new_download = Download(
        filename=filename,
        state="queued",
        progress=0.0,
        username=original.username,
        priority=priority,
    )
    session.add(new_download)
    session.flush()

    payload_copy["download_id"] = new_download.id
    payload_copy.setdefault("filename", filename)
    payload_copy["priority"] = priority
    new_download.request_payload = payload_copy

    try:
        await transfers.cancel_download(download_id)
    except TransfersApiError as exc:
        session.rollback()
        logger.error("slskd cancellation before retry failed for %s: %s", download_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to cancel existing download via slskd",
        ) from exc

    try:
        await transfers.enqueue(username=original.username, files=[payload_copy])
    except TransfersApiError as exc:
        session.rollback()
        logger.error("Failed to enqueue retry for download %s: %s", download_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to enqueue download via slskd",
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive unexpected failure
        session.rollback()
        logger.exception("Unexpected error while retrying download %s: %s", download_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retry download",
        ) from exc

    try:
        session.commit()
    except Exception as exc:  # pragma: no cover - defensive persistence handling
        session.rollback()
        logger.exception("Failed to persist retry download for %s: %s", download_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retry download",
        ) from exc

    record_activity(
        "download",
        "download_retried",
        details={
            "original_download_id": download_id,
            "retry_download_id": new_download.id,
            "username": original.username,
            "filename": filename,
        },
    )

    response: Dict[str, Any] = {
        "status": "queued",
        "download_id": new_download.id,
    }
    return response
