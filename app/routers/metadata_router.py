"""Routes that manage the metadata refresh workflow."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app import dependencies
from app.logging import get_logger
from app.workers import MatchingWorker, MetadataUpdateWorker, ScanWorker
from app.workers.metadata_worker import MetadataUpdateRunningError

router = APIRouter(prefix="/api/metadata", tags=["Metadata"])
logger = get_logger(__name__)


def _get_worker(request: Request) -> MetadataUpdateWorker:
    worker = getattr(request.app.state, "metadata_worker", None)
    if worker is not None:
        return worker

    scan_worker = getattr(request.app.state, "scan_worker", None)
    if scan_worker is None:
        try:
            plex_client = dependencies.get_plex_client()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Scan worker unavailable for metadata update")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Scan worker unavailable",
            ) from exc
        scan_worker = ScanWorker(plex_client)
        request.app.state.scan_worker = scan_worker

    matching_worker = getattr(request.app.state, "matching_worker", None)
    if matching_worker is None:
        try:
            engine = dependencies.get_matching_engine()
        except Exception:  # pragma: no cover - defensive
            engine = None
        if engine is not None:
            matching_worker = MatchingWorker(engine)
            request.app.state.matching_worker = matching_worker

    worker = MetadataUpdateWorker(scan_worker, matching_worker)
    request.app.state.metadata_worker = worker
    return worker


@router.post("/update", status_code=status.HTTP_202_ACCEPTED)
async def start_metadata_update(request: Request) -> dict[str, object]:
    """Kick off a metadata update job."""

    worker = _get_worker(request)
    try:
        state = await worker.start()
    except MetadataUpdateRunningError as exc:
        logger.warning("Metadata update already running")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Metadata update already running") from exc
    return {"message": "Metadata update started", "state": state}


@router.get("/status")
async def get_metadata_status(request: Request) -> dict[str, object]:
    """Return the current metadata job status."""

    worker = _get_worker(request)
    return worker.status()


@router.post("/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_metadata_update(request: Request) -> dict[str, object]:
    """Request to stop the running metadata job."""

    worker = _get_worker(request)
    state = await worker.stop()
    return {"message": "Stop signal issued", "state": state}

