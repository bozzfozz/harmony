"""Soulseek API endpoints."""

from __future__ import annotations

import asyncio
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.soulseek_client import SoulseekClient, SoulseekClientError
from app.db import session_scope
from app.dependencies import get_db, get_soulseek_client
from app.logging import get_logger
from app.models import DiscographyJob, Download
from app.schemas import (
    DiscographyDownloadRequest,
    DiscographyJobResponse,
    DownloadMetadataResponse,
    SoulseekCancelResponse,
    SoulseekDownloadRequest,
    SoulseekDownloadResponse,
    SoulseekDownloadStatus,
    SoulseekSearchRequest,
    SoulseekSearchResponse,
    StatusResponse,
)
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app.workers.sync_worker import SyncWorker
from app.utils import artwork_utils

logger = get_logger(__name__)

router = APIRouter()


def _translate_error(message: str, exc: SoulseekClientError) -> HTTPException:
    logger.error("%s: %s", message, exc)
    return HTTPException(status_code=502, detail=message)


@router.get("/status", response_model=StatusResponse)
async def soulseek_status(
    client: SoulseekClient = Depends(get_soulseek_client),
) -> StatusResponse:
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
            download = Download(
                filename=filename,
                state="queued",
                progress=0.0,
                username=payload.username,
                retry_count=0,
                next_retry_at=None,
                last_error=None,
            )
            session.add(download)
            session.flush()

            payload_copy = dict(file_info)
            payload_copy.setdefault("filename", filename)
            payload_copy["download_id"] = download.id

            try:
                priority_value = int(payload_copy.get("priority", download.priority) or 0)
            except (TypeError, ValueError):
                priority_value = 0

            download.priority = priority_value or download.priority
            download.request_payload = {
                "file": dict(payload_copy),
                "username": payload.username,
                "priority": priority_value,
            }
            download.next_retry_at = None
            download.last_error = None
            session.add(download)

            payload_copy.setdefault("priority", priority_value)
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
                    "copyright": download.copyright,
                    "artwork_url": download.artwork_url,
                    "artwork_path": download.artwork_path,
                    "artwork_status": download.artwork_status,
                    "has_artwork": download.has_artwork,
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


@router.get("/download/{download_id}/lyrics")
def soulseek_download_lyrics(
    download_id: int,
    session: Session = Depends(get_db),
) -> Response:
    """Return the generated LRC lyrics for a completed download."""

    download = session.get(Download, download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="Download not found")

    status = (download.lyrics_status or "").lower()
    if download.has_lyrics and download.lyrics_path:
        lyrics_path = Path(download.lyrics_path)
        if not lyrics_path.exists():
            raise HTTPException(status_code=404, detail="Lyrics file not found")
    else:
        if status in {"", "pending"}:
            return JSONResponse(status_code=202, content={"status": "pending"})
        if status == "failed":
            raise HTTPException(status_code=502, detail="Lyrics generation failed")
        raise HTTPException(status_code=404, detail="Lyrics file not available")

    lyrics_path = Path(download.lyrics_path)
    if not lyrics_path.exists():
        raise HTTPException(status_code=404, detail="Lyrics file not found")

    try:
        content = lyrics_path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to read lyrics file %s: %s", lyrics_path, exc)
        raise HTTPException(status_code=500, detail="Unable to read lyrics file") from exc

    return PlainTextResponse(content, media_type="text/plain; charset=utf-8")


@router.post("/download/{download_id}/lyrics/refresh")
async def refresh_download_lyrics(
    download_id: int,
    request: Request,
    session: Session = Depends(get_db),
) -> JSONResponse:
    """Force a new lyrics lookup for the given download."""

    download = session.get(Download, download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="Download not found")

    worker = getattr(request.app.state, "lyrics_worker", None)
    if worker is None or not hasattr(worker, "enqueue"):
        raise HTTPException(status_code=503, detail="Lyrics worker unavailable")

    if not download.filename:
        raise HTTPException(status_code=400, detail="Download has no filename")

    track_info = _build_track_info(download)
    track_info.setdefault("filename", download.filename)
    track_info.setdefault("download_id", download.id)

    await worker.enqueue(download.id, download.filename, track_info)

    download.lyrics_status = "pending"
    download.has_lyrics = False
    download.updated_at = datetime.utcnow()
    session.add(download)
    session.commit()

    return JSONResponse(status_code=202, content={"status": "queued"})


@router.get(
    "/download/{download_id}/metadata",
    response_model=DownloadMetadataResponse,
)
def soulseek_download_metadata(
    download_id: int,
    session: Session = Depends(get_db),
) -> DownloadMetadataResponse:
    """Return the stored metadata for a completed download."""

    download = session.get(Download, download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="Download not found")

    return DownloadMetadataResponse.model_validate(download)


@router.post("/download/{download_id}/metadata/refresh")
async def refresh_download_metadata(
    download_id: int,
    request: Request,
    session: Session = Depends(get_db),
) -> JSONResponse:
    """Trigger a metadata refresh for the given download."""

    download = session.get(Download, download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="Download not found")

    worker = getattr(request.app.state, "rich_metadata_worker", None)
    if worker is None or not hasattr(worker, "enqueue"):
        raise HTTPException(status_code=503, detail="Metadata worker unavailable")

    if not download.filename:
        raise HTTPException(status_code=400, detail="Download has no filename")

    audio_path = Path(download.filename)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    payload = dict(download.request_payload or {})

    async def _run_refresh() -> None:
        try:
            await worker.enqueue(
                download.id,
                audio_path,
                payload=payload,
                request_payload=dict(download.request_payload or {}),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Metadata refresh failed for %s: %s", download_id, exc)

    asyncio.create_task(_run_refresh())
    return JSONResponse(status_code=202, content={"status": "queued"})


def _build_track_info(download: Download) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    sources = _collect_track_sources(download)

    filename = download.filename or ""
    stem = Path(filename).stem if filename else ""

    title = _resolve_track_field(("title", "name", "track"), sources, default=stem)
    if title:
        info["title"] = title

    artist = _resolve_track_field(("artist", "artist_name", "artists"), sources)
    if artist:
        info["artist"] = artist

    album = _resolve_track_field(("album", "album_name", "release"), sources)
    if album:
        info["album"] = album

    duration = _resolve_numeric_field(("duration", "duration_ms", "durationMs", "length"), sources)
    if duration is not None:
        info["duration"] = duration

    for source in sources:
        spotify_track_id = SyncWorker._extract_spotify_id(source)
        if spotify_track_id:
            info["spotify_track_id"] = spotify_track_id
            break

    return info


def _collect_track_sources(download: Download) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    payload = download.request_payload or {}
    if isinstance(payload, dict):
        sources.append(payload)
        for key in ("metadata", "track", "info"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                sources.append(nested)
    return sources


def _resolve_track_field(
    keys: tuple[str, ...],
    sources: List[Dict[str, Any]],
    *,
    default: str = "",
) -> str:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if isinstance(value, dict):
                nested = value.get("name")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
            if isinstance(value, list) and value:
                first = value[0]
                if isinstance(first, dict):
                    nested = first.get("name")
                    if isinstance(nested, str) and nested.strip():
                        return nested.strip()
                elif isinstance(first, str) and first.strip():
                    return first.strip()
            if isinstance(value, str) and value.strip():
                return value.strip()
    return default


def _resolve_numeric_field(
    keys: tuple[str, ...],
    sources: List[Dict[str, Any]],
) -> float | None:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            return numeric
    return None


@router.get("/download/{download_id}/artwork")
def soulseek_download_artwork(
    download_id: int,
    session: Session = Depends(get_db),
) -> Response:
    """Return the stored artwork as an image file."""

    download = session.get(Download, download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="Download not found")

    if not download.has_artwork or not download.artwork_path:
        raise HTTPException(status_code=404, detail="Artwork not available")

    artwork_path = Path(download.artwork_path)
    if not artwork_path.exists():
        raise HTTPException(status_code=404, detail="Artwork file not found")

    media_type = mimetypes.guess_type(str(artwork_path))[0] or "image/jpeg"
    return FileResponse(artwork_path, media_type=media_type, filename=artwork_path.name)


@router.post("/download/{download_id}/artwork/refresh")
async def soulseek_refresh_artwork(
    download_id: int,
    request: Request,
    session: Session = Depends(get_db),
) -> JSONResponse:
    """Force an artwork refresh for a completed download."""

    download = session.get(Download, download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="Download not found")

    audio_path = Path(download.filename)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    request_payload = download.request_payload if isinstance(download.request_payload, dict) else {}
    metadata: Dict[str, Any] = {}
    nested_metadata = request_payload.get("metadata") if isinstance(request_payload, dict) else {}
    if isinstance(nested_metadata, dict):
        metadata.update(nested_metadata)
    if isinstance(request_payload, dict):
        for key in ("album", "artwork_urls", "spotify_album_id", "album_id"):
            value = request_payload.get(key)
            if value is not None and key not in metadata:
                metadata[key] = value
    if download.artwork_url and "artwork_url" not in metadata:
        metadata["artwork_url"] = download.artwork_url

    spotify_track_id = SyncWorker._extract_spotify_id(request_payload)
    if not spotify_track_id:
        spotify_track_id = SyncWorker._extract_spotify_id(metadata)
    if not spotify_track_id and download.spotify_track_id:
        spotify_track_id = download.spotify_track_id

    spotify_album_id = SyncWorker._extract_spotify_album_id(metadata, request_payload)
    if not spotify_album_id and download.spotify_album_id:
        spotify_album_id = download.spotify_album_id

    if spotify_track_id:
        download.spotify_track_id = spotify_track_id
    if spotify_album_id:
        download.spotify_album_id = spotify_album_id

    inferred_album = artwork_utils.infer_spotify_album_id(download)
    if inferred_album and not spotify_album_id:
        spotify_album_id = inferred_album
        download.spotify_album_id = inferred_album

    download.artwork_status = "pending"
    download.artwork_path = None
    download.has_artwork = False
    download.updated_at = datetime.utcnow()
    session.add(download)
    session.commit()

    if spotify_album_id and "spotify_album_id" not in metadata:
        metadata["spotify_album_id"] = spotify_album_id

    worker = getattr(request.app.state, "artwork_worker", None)
    if worker is None or not hasattr(worker, "enqueue"):
        return JSONResponse(status_code=202, content={"status": "pending"})

    try:
        await worker.enqueue(
            download.id,
            str(audio_path),
            metadata=metadata,
            spotify_track_id=spotify_track_id,
            spotify_album_id=spotify_album_id,
            artwork_url=metadata.get("artwork_url"),
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to refresh artwork for download %s: %s", download.id, exc)
        raise HTTPException(status_code=502, detail="Failed to refresh artwork") from exc

    return JSONResponse(status_code=202, content={"status": "pending"})


@router.post("/discography/download", response_model=DiscographyJobResponse)
async def soulseek_discography_download(
    payload: DiscographyDownloadRequest,
    request: Request,
    session: Session = Depends(get_db),
) -> DiscographyJobResponse:
    """Persist and enqueue a complete discography download job."""

    if not payload.artist_id:
        raise HTTPException(status_code=400, detail="Artist identifier is required")

    job = DiscographyJob(
        artist_id=payload.artist_id,
        artist_name=payload.artist_name,
        status="pending",
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    worker = getattr(request.app.state, "discography_worker", None)
    try:
        if worker is not None and hasattr(worker, "enqueue"):
            await worker.enqueue(job.id)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to enqueue discography job %s: %s", job.id, exc)

    return DiscographyJobResponse(job_id=job.id, status=job.status)


@router.get("/downloads", response_model=SoulseekDownloadStatus)
def soulseek_downloads(session: Session = Depends(get_db)) -> SoulseekDownloadStatus:
    """Return persisted download progress from the database."""

    stmt = select(Download).order_by(Download.created_at.desc())
    downloads = session.execute(stmt).scalars().all()
    return SoulseekDownloadStatus(downloads=downloads)


@router.post("/downloads/{download_id}/requeue", status_code=202)
async def soulseek_requeue_download(
    download_id: int,
    request: Request,
    session: Session = Depends(get_db),
) -> JSONResponse:
    """Manually requeue a download unless it resides in the dead-letter queue."""

    download = session.get(Download, download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="Download not found")

    if download.state == "dead_letter":
        raise HTTPException(status_code=409, detail="Download is in the dead-letter queue")

    if download.state in {"queued", "downloading"}:
        raise HTTPException(status_code=409, detail="Download is already active")

    worker = getattr(request.app.state, "sync_worker", None)
    if worker is None or not hasattr(worker, "enqueue"):
        raise HTTPException(status_code=503, detail="Sync worker unavailable")

    request_payload = dict(download.request_payload or {})
    file_info = request_payload.get("file")
    if not isinstance(file_info, dict):
        raise HTTPException(status_code=409, detail="Download cannot be requeued")

    username = request_payload.get("username") or download.username
    if not username:
        raise HTTPException(status_code=409, detail="Download username missing for retry")

    priority_value = SyncWorker._coerce_priority(
        file_info.get("priority") or request_payload.get("priority") or download.priority
    )

    file_payload = dict(file_info)
    file_payload["download_id"] = download.id
    file_payload.setdefault("priority", priority_value)

    job = {
        "username": username,
        "files": [file_payload],
        "priority": priority_value,
    }

    download.job_id = None
    download.state = "queued"
    download.retry_count = 0
    download.next_retry_at = None
    download.last_error = None
    download.updated_at = datetime.utcnow()
    request_payload.update(
        {
            "file": dict(file_payload),
            "username": username,
            "priority": priority_value,
        }
    )
    download.request_payload = request_payload

    session.add(download)
    session.commit()

    try:
        await worker.enqueue(job)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to requeue download %s: %s", download_id, exc)
        with session_scope() as recovery:
            record = recovery.get(Download, download_id)
            if record is not None:
                record.state = "failed"
                record.last_error = str(exc)
                record.updated_at = datetime.utcnow()
        raise HTTPException(status_code=502, detail="Failed to requeue download") from exc

    return JSONResponse(status_code=202, content={"status": "enqueued"})


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
async def soulseek_all_downloads(
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
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
async def soulseek_uploads(
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
    try:
        uploads = await client.get_uploads()
    except SoulseekClientError as exc:
        raise _translate_error("Failed to fetch uploads", exc) from exc
    return {"uploads": uploads}


@router.get("/uploads/all")
async def soulseek_all_uploads(
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Dict[str, Any]:
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
