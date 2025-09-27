"""Routes that manage the metadata refresh workflow."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.logging import get_logger

router = APIRouter(prefix="/api/metadata", tags=["Metadata"])
logger = get_logger(__name__)


@router.post("/update", status_code=status.HTTP_202_ACCEPTED)
async def start_metadata_update(request: Request) -> dict[str, object]:
    """Kick off a metadata update job."""

    logger.info("Metadata update requested but Plex integration is disabled")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Metadata update disabled while Plex integration is archived",
    )


@router.get("/status")
async def get_metadata_status(request: Request) -> dict[str, object]:
    """Return the current metadata job status."""

    logger.info("Metadata status requested but Plex integration is disabled")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Metadata update disabled while Plex integration is archived",
    )


@router.post("/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_metadata_update(request: Request) -> dict[str, object]:
    """Request to stop the running metadata job."""

    logger.info("Metadata stop requested but Plex integration is disabled")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Metadata update disabled while Plex integration is archived",
    )
