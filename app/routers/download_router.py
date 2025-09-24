"""Download management endpoints for Harmony."""
from __future__ import annotations

import inspect
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.logging import get_logger
from app.models import Download
from app.schemas import (
    DownloadEntryResponse,
    DownloadListResponse,
    SoulseekDownloadRequest,
)
from app.utils.activity import record_activity

router = APIRouter(prefix="/api", tags=["Download"])
logger = get_logger(__name__)


async def _maybe_await(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


@router.get("/downloads", response_model=DownloadListResponse)
def list_downloads(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    all: bool = False,  # noqa: A002 - query parameter name mandated by API contract
    session: Session = Depends(get_db),
) -> DownloadListResponse:
    """Return downloads, optionally including completed or failed entries."""

    logger.info("Download list requested (all=%s, limit=%s, offset=%s)", all, limit, offset)
    try:
        query = session.query(Download)
        if not all:
            query = query.filter(Download.state.in_(("queued", "running")))
        downloads = (
            query.order_by(Download.created_at.desc()).offset(offset).limit(limit).all()
        )
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
        for file_info in payload.files:
            filename = str(file_info.get("filename") or file_info.get("name") or "unknown")
            download = Download(
                filename=filename,
                state="queued",
                progress=0.0,
                username=payload.username,
            )
            session.add(download)
            session.flush()

            payload_copy = dict(file_info)
            payload_copy.setdefault("filename", filename)
            payload_copy["download_id"] = download.id
            download.request_payload = payload_copy
            job_files.append(payload_copy)

            download_records.append(download)
        session.commit()
    except Exception as exc:  # pragma: no cover - defensive persistence handling
        session.rollback()
        logger.exception("Failed to persist download request: %s", exc)
        record_activity("download", "failed", details={"reason": "persistence_error"})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to queue download") from exc

    job = {"username": payload.username, "files": job_files}
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
    request: Request,
    session: Session = Depends(get_db),
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

    worker = getattr(request.app.state, "sync_worker", None)
    cancel_func = getattr(worker, "request_cancel", None)
    if cancel_func is not None:
        try:
            await _maybe_await(cancel_func(download_id))
        except Exception as exc:  # pragma: no cover - defensive worker error handling
            logger.warning("Failed to signal cancellation for download %s: %s", download_id, exc)

    record_activity(
        "download",
        "download_cancelled",
        details={"download_id": download_id, "filename": download.filename},
    )

    return {"status": "cancelled", "download_id": download_id}


@router.post("/download/{download_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_download(
    download_id: int,
    request: Request,
    session: Session = Depends(get_db),
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

    new_download = Download(
        filename=original.filename,
        state="queued",
        progress=0.0,
        username=original.username,
    )
    session.add(new_download)
    session.flush()

    payload_copy["download_id"] = new_download.id
    payload_copy.setdefault("filename", new_download.filename)
    new_download.request_payload = payload_copy

    try:
        session.commit()
    except Exception as exc:  # pragma: no cover - defensive persistence handling
        session.rollback()
        logger.exception("Failed to persist retry download for %s: %s", download_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retry download",
        ) from exc

    worker = getattr(request.app.state, "sync_worker", None)
    enqueue = getattr(worker, "enqueue", None)
    if enqueue is None:
        logger.error("Retry failed for %s: download worker unavailable", download_id)
        record_activity(
            "download",
            "download_retried",
            details={
                "original_download_id": download_id,
                "retry_download_id": new_download.id,
                "status": "worker_unavailable",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Download worker unavailable",
        )

    job = {"username": original.username, "files": [payload_copy]}
    try:
        await enqueue(job)
    except Exception as exc:  # pragma: no cover - defensive worker error
        logger.exception("Failed to enqueue retry for download %s: %s", download_id, exc)
        now = datetime.utcnow()
        new_download.state = "failed"
        new_download.updated_at = now
        session.commit()
        record_activity(
            "download",
            "download_retried",
            details={
                "original_download_id": download_id,
                "retry_download_id": new_download.id,
                "status": "enqueue_error",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to enqueue download",
        ) from exc

    record_activity(
        "download",
        "download_retried",
        details={
            "original_download_id": download_id,
            "retry_download_id": new_download.id,
            "username": original.username,
        },
    )

    response: Dict[str, Any] = {
        "status": "queued",
        "download_id": new_download.id,
    }
    return response
