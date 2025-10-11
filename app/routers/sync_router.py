"""Routes coordinating manual sync operations."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import dependencies
from app.dependencies import SessionRunner, get_session_runner
from app.logging import get_logger
from app.logging_events import log_event
from app.utils.activity import record_activity
from app.utils.events import SYNC_BLOCKED
from app.utils.service_health import collect_missing_credentials
from app.workers.playlist_sync_worker import PlaylistSyncWorker

router = APIRouter(tags=["Sync"])
logger = get_logger(__name__)


REQUIRED_SERVICES: tuple[str, ...] = ("spotify", "soulseek")


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_manual_sync(
    request: Request,
    session_runner: SessionRunner = Depends(get_session_runner),
) -> dict[str, Any]:
    """Run playlist and library synchronisation tasks on demand."""

    missing = await _missing_credentials(session_runner)
    if missing:
        missing_payload = {service: list(values) for service, values in missing.items()}
        log_event(
            logger,
            "api.sync.trigger",
            component="router.sync",
            status="blocked",
            entity_id=None,
            meta={"missing": missing_payload},
        )
        record_activity(
            "sync",
            SYNC_BLOCKED,
            details={"missing": missing_payload},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Sync blocked", "missing": missing_payload},
        )

    playlist_worker = _get_playlist_worker(request)
    sources = ["spotify", "soulseek"]
    record_activity("sync", "sync_started", details={"mode": "manual", "sources": sources})

    results: Dict[str, str] = {}
    errors: Dict[str, str] = {}

    if playlist_worker is not None:
        try:
            await playlist_worker.sync_once()
            results["playlists"] = "completed"
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Playlist sync failed: %s", exc)
            errors["playlists"] = str(exc)
    else:
        errors["playlists"] = "Playlist worker unavailable"

    errors["library_scan"] = "Library scan disabled"
    errors["auto_sync"] = "AutoSync worker disabled"

    response: Dict[str, Any] = {"message": "Sync triggered", "results": results}
    if errors:
        response["errors"] = errors

    counters = {
        "tracks_synced": 0,
        "tracks_skipped": 0,
        "errors": len(errors),
    }
    if errors:
        error_list = [{"source": key, "message": value} for key, value in sorted(errors.items())]
        record_activity(
            "sync",
            "sync_partial",
            details={
                "mode": "manual",
                "sources": sources,
                "results": results,
                "errors": error_list,
            },
        )

    record_activity(
        "sync",
        "sync_completed",
        details={
            "mode": "manual",
            "sources": sources,
            "results": results,
            "counters": counters,
        },
    )
    return response


def _get_playlist_worker(request: Request) -> PlaylistSyncWorker | None:
    worker = getattr(request.app.state, "playlist_worker", None)
    if isinstance(worker, PlaylistSyncWorker):
        return worker
    try:
        spotify_client = dependencies.get_spotify_client()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Unable to initialise Spotify client for playlist sync: %s", exc)
        return None
    response_cache = getattr(request.app.state, "response_cache", None)
    worker = PlaylistSyncWorker(
        spotify_client,
        interval_seconds=900.0,
        response_cache=response_cache,
    )
    request.app.state.playlist_worker = worker
    return worker


async def _missing_credentials(
    session_runner: SessionRunner,
) -> dict[str, tuple[str, ...]]:
    def _query(session: Session) -> dict[str, tuple[str, ...]]:
        return collect_missing_credentials(session, REQUIRED_SERVICES)

    return await session_runner(_query)
