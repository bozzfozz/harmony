"""API endpoints for managing synchronisation jobs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.utils.logging_config import get_logger
from backend.app.models.sync_job import SyncJob
from backend.app.workers.sync_worker import SyncWorker

logger = get_logger("sync_router")

router = APIRouter(prefix="/sync", tags=["Sync"])

worker = SyncWorker()


def _serialize_job(job: SyncJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "spotify_id": job.spotify_id,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "error_message": job.error_message,
    }


@router.post("/start/{spotify_id}")
async def start_sync_job(spotify_id: str) -> dict[str, Any]:
    """Create a new synchronisation job and launch the worker."""

    try:
        job_id = await worker.start_sync(spotify_id)
    except Exception as exc:  # pragma: no cover - defensive safety net
        logger.error("Failed to start sync for %s: %s", spotify_id, exc)
        raise HTTPException(status_code=500, detail="Failed to start sync job") from exc

    return {"job_id": job_id, "status": "pending"}


@router.get("/status/{job_id}")
def get_sync_status(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return the current status for a sync job."""

    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Sync job not found")

    return _serialize_job(job)


@router.get("/all")
def list_sync_jobs(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return a list of all synchronisation jobs."""

    jobs = db.query(SyncJob).order_by(SyncJob.created_at.desc()).all()
    return {"jobs": [_serialize_job(job) for job in jobs]}
