"""Spotify backfill router delegating to :mod:`SpotifyDomainService`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.dependencies import get_app_config, get_soulseek_client, get_spotify_client
from app.services.backfill_service import BackfillJobStatus
from app.services.spotify_domain_service import SpotifyDomainService

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


def _get_spotify_service(
    request: Request,
    config=Depends(get_app_config),
    spotify_client: SpotifyClient = Depends(get_spotify_client),
    soulseek_client: SoulseekClient = Depends(get_soulseek_client),
) -> SpotifyDomainService:
    return SpotifyDomainService(
        config=config,
        spotify_client=spotify_client,
        soulseek_client=soulseek_client,
        app_state=request.app.state,
    )


@router.post("/run", response_model=BackfillRunResponse)
async def run_backfill(
    payload: BackfillRunRequest,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> JSONResponse:
    if not service.is_authenticated():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Spotify credentials are required for backfill",
        )

    try:
        job = service.create_backfill_job(
            max_items=payload.max_items,
            expand_playlists=payload.expand_playlists,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Spotify credentials are required for backfill",
        ) from None

    await service.enqueue_backfill_job(job)
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
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> BackfillJobResponse:
    status_payload = service.get_backfill_status(job_id)
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


__all__ = ["router"]
