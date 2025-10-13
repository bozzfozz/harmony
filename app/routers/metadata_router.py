"""Routes that manage the metadata refresh workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, status

from app.logging import get_logger
from app.logging_events import log_event

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.workers.metadata_worker import MetadataUpdateWorker

router = APIRouter(prefix="/metadata", tags=["Metadata"])
logger = get_logger(__name__)


@router.post("/update", status_code=status.HTTP_202_ACCEPTED)
async def start_metadata_update(request: Request) -> dict[str, object]:
    """Kick off a metadata update job."""

    worker = _resolve_worker(request)
    try:
        payload = await worker.start()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    log_event(
        logger,
        "api.metadata.request",
        component="router.metadata",
        status="accepted",
        entity_id=None,
        action="update",
        job_status=str(payload.get("status")),
    )
    return payload


@router.get("/status")
async def get_metadata_status(request: Request) -> dict[str, object]:
    """Return the current metadata job status."""

    worker = _resolve_worker(request)
    payload = await worker.status()
    log_event(
        logger,
        "api.metadata.request",
        component="router.metadata",
        status="ok",
        entity_id=None,
        action="status",
        job_status=str(payload.get("status")),
    )
    return payload


@router.post("/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_metadata_update(request: Request) -> dict[str, object]:
    """Request to stop the running metadata job."""

    worker = _resolve_worker(request)
    payload = await worker.stop()
    log_event(
        logger,
        "api.metadata.request",
        component="router.metadata",
        status="accepted",
        entity_id=None,
        action="stop",
        job_status=str(payload.get("status")),
    )
    return payload


def _resolve_worker(request: Request) -> MetadataUpdateWorker:
    worker = getattr(request.app.state, "metadata_update_worker", None)
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metadata update worker unavailable",
        )
    return worker
