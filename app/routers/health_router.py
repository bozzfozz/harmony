"""Health endpoints for external service integrations."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas import ServiceHealthResponse
from app.utils.service_health import evaluate_service_health

router = APIRouter()


@router.get("/spotify", response_model=ServiceHealthResponse)
def spotify_health(session: Session = Depends(get_db)) -> ServiceHealthResponse:
    result = evaluate_service_health(session, "spotify")
    return ServiceHealthResponse(
        service=result.service,
        status=result.status,
        missing=list(result.missing),
        optional_missing=list(result.optional_missing),
    )


@router.get("/plex", response_model=ServiceHealthResponse)
def plex_health(session: Session = Depends(get_db)) -> ServiceHealthResponse:
    result = evaluate_service_health(session, "plex")
    return ServiceHealthResponse(
        service=result.service,
        status=result.status,
        missing=list(result.missing),
        optional_missing=list(result.optional_missing),
    )


@router.get("/soulseek", response_model=ServiceHealthResponse)
def soulseek_health(session: Session = Depends(get_db)) -> ServiceHealthResponse:
    result = evaluate_service_health(session, "soulseek")
    return ServiceHealthResponse(
        service=result.service,
        status=result.status,
        missing=list(result.missing),
        optional_missing=list(result.optional_missing),
    )
