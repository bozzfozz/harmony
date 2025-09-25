"""Soulseek API endpoints."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.soulseek_client import SoulseekClient, SoulseekClientError
from app.dependencies import get_db, get_soulseek_client
from app.logging import get_logger
from app.models import Download
from app.schemas import (
    SoulseekCancelResponse,
    SoulseekDownloadRequest,
    SoulseekDownloadResponse,
    SoulseekDownloadStatus,
    SoulseekSearchRequest,
    SoulseekSearchResponse,
    StatusResponse,
)

logger = get_logger(__name__)

router = APIRouter()


def _translate_error(message: str, exc: SoulseekClientError) -> HTTPException:
    logger.error("%s: %s", message, exc)
    return HTTPException(status_code=502, detail=message)


@router.get("/status", response_model=StatusResponse)
async def soulseek_status(client: SoulseekClient = Depends(get_soulseek_client)) -> StatusResponse:
    """Return connectivity status for the Soulseek daemon."""

    try:
        await client.get_download_status()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Soulseek status check failed: %s", exc)
        return StatusResponse(status="disconnected")
    return StatusResponse(status="connected")


@router.post("/search", response_model=SoulseekSearchResponse)
async def soulseek_search(
    payload: SoulseekSearchRequest,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> SoulseekSearchResponse:
    """Perform a Soulseek search and normalise the JSON response."""

    try:
        results = await client.search(payload.query)
    except SoulseekClientError as exc:
        logger.error("Soulseek search failed: %s", exc)
        raise HTTPException(status_code=502, detail="Soulseek search failed") from exc
    items: list[Any]
    raw_payload: Dict[str, Any] | None = None
    if isinstance(results, dict):
        raw_payload = results
        extracted = results.get("results", [])
        items = extracted if isinstance(extracted, list) else [extracted]
    elif isinstance(results, list):
        items = results
    else:
        items = [results] if results else []
    return SoulseekSearchResponse(results=items, raw=raw_payload)


@router.post("/download", response_model=SoulseekDownloadResponse)
async def soulseek_download(
    payload: SoulseekDownloadRequest,
    request: Request,
    session: Session = Depends(get_db),
    client: SoulseekClient = Depends(get_soulseek_client),
) -> SoulseekDownloadResponse:
    """Queue a Soulseek download job and persist queued entries."""

    if not payload.files:
        raise HTTPException(status_code=400, detail="No files provided for download")

    created_downloads: List[Dict[str, Any]] = []
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

            created_downloads.append(
                {
                    "id": download.id,
                    "filename": filename,
                    "state": download.state,
                    "progress": download.progress,
                    "genre": download.genre,
                    "composer": download.composer,
                    "producer": download.producer,
                    "isrc": download.isrc,
                    "artwork_url": download.artwork_url,
                }
            )
        session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        session.rollback()
        logger.error("Failed to persist download request: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to queue download") from exc

    job = {"username": payload.username, "files": job_files}

    worker = getattr(request.app.state, "sync_worker", None)
    try:
        if worker is not None and hasattr(worker, "enqueue"):
            await worker.enqueue(job)
        else:
            await client.download(job)
    except Exception as exc:
        if isinstance(exc, asyncio.CancelledError):  # pragma: no cover - defensive
            raise
        logger.error("Soulseek rejected download queue request: %s", exc)
        for record in job_files:
            download = session.get(Download, record["download_id"])
            if download is None:
                continue
            download.state = "failed"
            download.updated_at = datetime.utcnow()
        session.commit()
        raise HTTPException(status_code=502, detail="Soulseek download failed") from exc

    detail: Dict[str, Any] = {"downloads": created_downloads}
    return SoulseekDownloadResponse(status="queued", detail=detail)


@router.get("/downloads", response_model=SoulseekDownloadStatus)
def soulseek_downloads(session: Session = Depends(get_db)) -> SoulseekDownloadStatus:
    """Return persisted download progress from the database."""

    stmt = select(Download).order_by(Download.created_at.desc())
    downloads = session.execute(stmt).scalars().all()
    return SoulseekDownloadStatus(downloads=downloads)


@router.delete("/download/{download_id}", response_model=SoulseekCancelResponse)
async def soulseek_cancel(
    download_id: int,
    session: Session = Depends(get_db),
    client: SoulseekClient = Depends(get_soulseek_client),
) -> SoulseekCancelResponse:
    """Cancel a Soulseek download by identifier."""

    download = session.get(Download, download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="Download not found")

    try:
        await client.cancel_download(str(download_id))
    except SoulseekClientError as exc:
        raise _translate_error("Failed to cancel download", exc)

    download.state = "failed"
    if download.progress < 0:
        download.progress = 0.0
    elif download.progress > 100:
        download.progress = 100.0
    download.updated_at = datetime.utcnow()
    session.commit()

    return SoulseekCancelResponse(cancelled=True)


@router.get("/download/{download_id}")
async def soulseek_download_detail(
    download_id: str,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.get_download(download_id)
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch download", exc) from exc


@router.get("/downloads/all")
async def soulseek_all_downloads(client: SoulseekClient = Depends(get_soulseek_client)) -> Dict[str, Any]:
    try:
        downloads = await client.get_all_downloads()
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch downloads", exc) from exc
    return {"downloads": downloads}


@router.delete("/downloads/completed")
async def soulseek_remove_completed_downloads(
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.remove_completed_downloads()
    except SoulseekClientError as exc:
        raise _translate_error("Failed to remove completed downloads", exc) from exc


@router.get("/download/{download_id}/queue")
async def soulseek_download_queue(
    download_id: str,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.get_queue_position(download_id)
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch queue position", exc) from exc


@router.post("/enqueue")
async def soulseek_enqueue(
    payload: SoulseekDownloadRequest,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.enqueue(payload.username, payload.files)
    except SoulseekClientError as exc:
        raise _translate_error("Failed to enqueue downloads", exc) from exc


@router.delete("/upload/{upload_id}")
async def soulseek_cancel_upload(
    upload_id: str,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.cancel_upload(upload_id)
    except SoulseekClientError as exc:
        raise _translate_error("Failed to cancel upload", exc) from exc


@router.get("/upload/{upload_id}")
async def soulseek_upload_detail(
    upload_id: str,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.get_upload(upload_id)
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch upload", exc) from exc


@router.get("/uploads")
async def soulseek_uploads(client: SoulseekClient = Depends(get_soulseek_client)) -> Dict[str, Any]:
    try:
        uploads = await client.get_uploads()
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch uploads", exc) from exc
    return {"uploads": uploads}


@router.get("/uploads/all")
async def soulseek_all_uploads(client: SoulseekClient = Depends(get_soulseek_client)) -> Dict[str, Any]:
    try:
        uploads = await client.get_all_uploads()
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch all uploads", exc) from exc
    return {"uploads": uploads}


@router.delete("/uploads/completed")
async def soulseek_remove_completed_uploads(
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.remove_completed_uploads()
    except SoulseekClientError as exc:
        raise _translate_error("Failed to remove completed uploads", exc) from exc


@router.get("/user/{username}/address")
async def soulseek_user_address(
    username: str,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.user_address(username)
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch user address", exc) from exc


@router.get("/user/{username}/browse")
async def soulseek_user_browse(
    username: str,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.user_browse(username)
    except SoulseekClientError as exc:
        raise _translate_error("Failed to browse user", exc) from exc


@router.get("/user/{username}/browsing_status")
async def soulseek_user_browsing_status(
    username: str,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.user_browsing_status(username)
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch user browsing status", exc) from exc


@router.get("/user/{username}/directory")
async def soulseek_user_directory(
    username: str,
    path: str = Query(..., description="Directory path to browse"),
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.user_directory(username, path)
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch user directory", exc) from exc


@router.get("/user/{username}/info")
async def soulseek_user_info(
    username: str,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.user_info(username)
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch user info", exc) from exc


@router.get("/user/{username}/status")
async def soulseek_user_status(
    username: str,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        return await client.user_status(username)
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch user status", exc) from exc
