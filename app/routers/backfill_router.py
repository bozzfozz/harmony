"""FastAPI router exposing Spotify backfill endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import AppConfig
from app.core.spotify_client import SpotifyClient
from app.dependencies import get_app_config, get_spotify_client
from app.services.backfill_service import BackfillJobStatus, BackfillService
from app.workers.backfill_worker import BackfillWorker

router = APIRouter()


class BackfillRunRequest(BaseModel):
    max_items: int | None = Field(default=None, ge=1, le=10_000)
    expand_playlists: bool = True


class BackfillRunResponse(BaseModel):
    ok: bool
    job_id: str


class BackfillJobCounts(BaseModel):
    requested: int
    processed: int
    matched: int
    cache_hits: int
    cache_misses: int
    expanded_playlists: int
    expanded_tracks: int


class BackfillJobResponse(BaseModel):
    ok: bool
    job_id: str
    state: str
    counts: BackfillJobCounts
    expand_playlists: bool
    duration_ms: int | None = None
    error: str | None = None


def _ensure_service(
    request: Request,
    config: AppConfig = Depends(get_app_config),
    client: SpotifyClient = Depends(get_spotify_client),
) -> BackfillService:
    service = getattr(request.app.state, "backfill_service", None)
    if not isinstance(service, BackfillService):
        service = BackfillService(config.spotify, client)
        request.app.state.backfill_service = service
    return service


async def _ensure_worker(
    request: Request,
    service: BackfillService = Depends(_ensure_service),
) -> BackfillWorker:
    worker = getattr(request.app.state, "backfill_worker", None)
    if not isinstance(worker, BackfillWorker):
        worker = BackfillWorker(service)
        request.app.state.backfill_worker = worker
        await worker.start()
    elif not worker.is_running():
        await worker.start()
    return worker


@router.post("/run", response_model=BackfillRunResponse)
async def run_backfill(
    payload: BackfillRunRequest,
    service: BackfillService = Depends(_ensure_service),
    worker: BackfillWorker = Depends(_ensure_worker),
    spotify_client: SpotifyClient = Depends(get_spotify_client),
) -> JSONResponse:
    try:
        authenticated = spotify_client.is_authenticated()
    except Exception:  # pragma: no cover - defensive guard
        authenticated = False
    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Spotify credentials are required for backfill",
        )

    try:
        job = service.create_job(
            max_items=payload.max_items,
            expand_playlists=payload.expand_playlists,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Spotify credentials are required for backfill",
        ) from None

    await worker.enqueue(job)
    response = BackfillRunResponse(ok=True, job_id=job.id)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=response.model_dump())


def _build_counts(status: BackfillJobStatus) -> BackfillJobCounts:
    return BackfillJobCounts(
        requested=status.requested_items,
        processed=status.processed_items,
        matched=status.matched_items,
        cache_hits=status.cache_hits,
        cache_misses=status.cache_misses,
        expanded_playlists=status.expanded_playlists,
        expanded_tracks=status.expanded_tracks,
    )


@router.get("/jobs/{job_id}", response_model=BackfillJobResponse)
async def get_backfill_job(
    job_id: str,
    service: BackfillService = Depends(_ensure_service),
) -> BackfillJobResponse:
    status_payload = service.get_status(job_id)
    if status_payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    counts = _build_counts(status_payload)
    return BackfillJobResponse(
        ok=True,
        job_id=status_payload.id,
        state=status_payload.state,
        counts=counts,
        expand_playlists=status_payload.expand_playlists,
        duration_ms=status_payload.duration_ms,
        error=status_payload.error,
    )
