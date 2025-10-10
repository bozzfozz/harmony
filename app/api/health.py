"""Health endpoints exposing liveness and readiness status."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from app.ops.selfcheck import ReadyReport, aggregate_ready

router = APIRouter(prefix="/api/health", tags=["Health"], include_in_schema=False)


@router.get("/live")
async def live() -> dict[str, str]:
    """Return a lightweight liveness response without dependency checks."""

    return {"status": "ok"}


@router.get("/ready")
async def ready(verbose: int = Query(0, ge=0, le=1)) -> Response:
    """Return readiness information with optional verbose diagnostics."""

    report: ReadyReport = aggregate_ready()
    payload = report.to_dict(verbose=bool(verbose))
    status_code = status.HTTP_200_OK if report.ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=payload)
