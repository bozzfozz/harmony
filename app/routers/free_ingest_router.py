"""FastAPI router for Spotify FREE ingest submissions."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.config import AppConfig
from app.dependencies import get_app_config, get_soulseek_client
from app.services.free_ingest_service import (
    FreeIngestService,
    IngestSubmission,
    PlaylistValidationError,
)
from app.workers.sync_worker import SyncWorker


router = APIRouter(prefix="/spotify/import", tags=["Spotify FREE Ingest"])


class FreeIngestRequest(BaseModel):
    playlist_links: list[str] = Field(default_factory=list)
    tracks: list[str] = Field(default_factory=list)
    batch_hint: Optional[int] = Field(default=None, ge=1, le=10_000)

    @field_validator("playlist_links", mode="before")
    @classmethod
    def _ensure_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        raise TypeError("playlist_links must be an array")

    @field_validator("tracks", mode="before")
    @classmethod
    def _ensure_tracks(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        raise TypeError("tracks must be an array")


class SubmissionAccepted(BaseModel):
    playlists: int
    tracks: int
    batches: int


class SubmissionSkipped(BaseModel):
    playlists: int
    tracks: int
    reason: Optional[str] = None


class SubmissionResponse(BaseModel):
    ok: bool
    job_id: Optional[str]
    accepted: SubmissionAccepted
    skipped: SubmissionSkipped
    error: Optional[Dict[str, Any]] = None


class JobCountsModel(BaseModel):
    registered: int
    normalized: int
    queued: int
    completed: int
    failed: int


class JobStatusModel(BaseModel):
    id: str
    state: str
    counts: JobCountsModel
    accepted: SubmissionAccepted
    skipped: SubmissionSkipped
    error: Optional[str] = None


class JobResponse(BaseModel):
    ok: bool
    job: JobStatusModel
    error: Optional[Dict[str, Any]] = None


def _resolve_sync_worker(request: Request) -> SyncWorker | None:
    worker = getattr(request.app.state, "sync_worker", None)
    return worker if isinstance(worker, SyncWorker) else None


def _get_service(
    request: Request,
    config: AppConfig = Depends(get_app_config),
    soulseek=Depends(get_soulseek_client),
) -> FreeIngestService:
    worker = _resolve_sync_worker(request)
    return FreeIngestService(config=config, soulseek_client=soulseek, sync_worker=worker)


def _build_submission_response(result: IngestSubmission) -> SubmissionResponse:
    skipped_payload = SubmissionSkipped(
        playlists=result.skipped.playlists,
        tracks=result.skipped.tracks,
        reason=result.skipped.reason,
    )
    accepted_payload = SubmissionAccepted(
        playlists=result.accepted.playlists,
        tracks=result.accepted.tracks,
        batches=result.accepted.batches,
    )
    error_payload: Optional[Dict[str, Any]] = None
    if result.error:
        code = "PARTIAL_SUCCESS" if result.error == "partial" else result.error.upper()
        error_payload = {"code": code, "message": result.error}
    return SubmissionResponse(
        ok=result.ok,
        job_id=result.job_id,
        accepted=accepted_payload,
        skipped=skipped_payload,
        error=error_payload,
    )


def _submission_status_code(result: IngestSubmission) -> int:
    if result.error or result.skipped.reason or result.skipped.playlists or result.skipped.tracks:
        return status.HTTP_207_MULTI_STATUS
    return status.HTTP_202_ACCEPTED


@router.post("/free", response_model=SubmissionResponse)
async def submit_free_ingest(
    payload: FreeIngestRequest,
    service: FreeIngestService = Depends(_get_service),
) -> JSONResponse:
    if not payload.playlist_links and not payload.tracks:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="playlist_links or tracks required",
        )

    try:
        result = await service.submit(
            playlist_links=payload.playlist_links,
            tracks=payload.tracks,
            batch_hint=payload.batch_hint,
        )
    except PlaylistValidationError as exc:
        details = [{"url": item.url, "reason": item.reason} for item in exc.invalid_links]
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="invalid playlist links",
            details=details,
        )

    response = _build_submission_response(result)
    status_code = _submission_status_code(result)
    return JSONResponse(status_code=status_code, content=response.model_dump())


@router.post("/free/upload", response_model=SubmissionResponse)
async def upload_free_ingest(
    request: Request,
    service: FreeIngestService = Depends(_get_service),
) -> JSONResponse:
    content_type = request.headers.get("content-type") or ""
    body = await request.body()
    try:
        filename, content = _parse_multipart_file(content_type, body)
    except ValueError as exc:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message=str(exc),
        )

    if not content:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="file is empty",
        )

    try:
        tracks = FreeIngestService.parse_tracks_from_file(content, filename)
    except ValueError as exc:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message=str(exc),
        )

    if not tracks:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="no tracks found in file",
        )

    result = await service.submit(tracks=tracks)
    response = _build_submission_response(result)
    status_code = _submission_status_code(result)
    return JSONResponse(status_code=status_code, content=response.model_dump())


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_free_ingest_job(
    job_id: str,
    service: FreeIngestService = Depends(_get_service),
) -> JobResponse:
    status_info = service.get_job_status(job_id)
    if status_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "job not found"},
        )

    counts = JobCountsModel(
        registered=status_info.counts.registered,
        normalized=status_info.counts.normalized,
        queued=status_info.counts.queued,
        completed=status_info.counts.completed,
        failed=status_info.counts.failed,
    )
    accepted = SubmissionAccepted(
        playlists=status_info.accepted.playlists,
        tracks=status_info.accepted.tracks,
        batches=status_info.accepted.batches,
    )
    skipped = SubmissionSkipped(
        playlists=status_info.skipped.playlists,
        tracks=status_info.skipped.tracks,
        reason=status_info.skipped.reason,
    )
    payload = JobStatusModel(
        id=status_info.id,
        state=status_info.state,
        counts=counts,
        accepted=accepted,
        skipped=skipped,
        error=status_info.error,
    )
    return JobResponse(ok=True, job=payload, error=None)


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: List[Dict[str, Any]] | None = None,
) -> JSONResponse:
    error_payload: Dict[str, Any] = {"code": code, "message": message}
    if details:
        error_payload["details"] = details
    content: Dict[str, Any] = {
        "ok": False,
        "job_id": None,
        "accepted": None,
        "skipped": {"playlists": 0, "tracks": 0, "reason": None},
        "error": error_payload,
    }
    return JSONResponse(status_code=status_code, content=content)


def _parse_multipart_file(content_type: str, body: bytes) -> Tuple[str, bytes]:
    if "multipart/form-data" not in content_type.lower():
        raise ValueError("expected multipart/form-data request")
    boundary_match = re.search(r"boundary=([^;]+)", content_type, flags=re.IGNORECASE)
    if not boundary_match:
        raise ValueError("missing multipart boundary")
    boundary = boundary_match.group(1).strip().strip('"')
    if not boundary:
        raise ValueError("invalid multipart boundary")
    delimiter = f"--{boundary}".encode("utf-8")
    closing = f"--{boundary}--".encode("utf-8")
    sections = body.split(delimiter)
    for section in sections:
        if not section or section.startswith(b"--"):
            continue
        part = section.strip(b"\r\n")
        if not part:
            continue
        if part == closing:
            continue
        header_blob, _, data = part.partition(b"\r\n\r\n")
        if not data:
            continue
        headers = {}
        for line in header_blob.split(b"\r\n"):
            if b":" not in line:
                continue
            name, value = line.split(b":", 1)
            headers[name.decode("utf-8", errors="ignore").strip().lower()] = value.decode(
                "utf-8", errors="ignore"
            ).strip()
        disposition = headers.get("content-disposition", "")
        if 'name="file"' not in disposition:
            continue
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        filename = filename_match.group(1) if filename_match else "upload.txt"
        content = data.rstrip(b"\r\n")
        return filename, content
    raise ValueError("no file part in request")
