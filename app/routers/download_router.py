"""Download management endpoints for Harmony."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
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


@router.get("/downloads", response_model=DownloadListResponse)
def list_downloads(
    all: bool = False,  # noqa: A002 - query parameter name mandated by API contract
    session: Session = Depends(get_db),
) -> DownloadListResponse:
    """Return downloads, optionally including completed or failed entries."""

    logger.info("Download list requested (all=%s)", all)
    try:
        query = session.query(Download)
        if not all:
            query = query.filter(Download.state.in_(("queued", "running")))
        downloads = query.order_by(Download.created_at.desc()).all()
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
            download = Download(filename=filename, state="queued", progress=0.0)
            session.add(download)
            session.flush()

            payload_copy = dict(file_info)
            payload_copy.setdefault("filename", filename)
            payload_copy["download_id"] = download.id
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
