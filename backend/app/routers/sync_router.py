from fastapi import APIRouter, HTTPException

from app.orchestrator.sync_worker import SyncWorker
from app.utils.logging_config import get_logger

logger = get_logger("sync_router")

router = APIRouter()

worker = SyncWorker()


@router.post("/track/{spotify_track_id}")
async def sync_track(spotify_track_id: str):
    """Trigger the end-to-end sync for a single Spotify track."""

    try:
        result = await worker.sync_track(spotify_track_id)
        return {"status": "ok", "data": result}
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Sync-Fehler: %s", exc)
        raise HTTPException(status_code=500, detail=f"Sync error: {exc}") from exc


@router.post("/playlist/{spotify_playlist_id}")
async def sync_playlist(spotify_playlist_id: str):
    """Trigger the sync for every track in a Spotify playlist."""

    try:
        playlist_tracks = worker.spotify.get_playlist_tracks(spotify_playlist_id)
        if not playlist_tracks:
            raise HTTPException(status_code=404, detail="Keine Tracks in Playlist gefunden")

        results = []
        for track in playlist_tracks:
            try:
                track_result = await worker.sync_track(track.id)
                results.append({"track": track.title, "status": "success", "data": track_result})
            except Exception as exc:  # pragma: no cover - continue processing other tracks
                logger.error("Fehler bei Track %s: %s", track.title, exc)
                results.append({"track": track.title, "status": "failed", "error": str(exc)})

        return {"status": "ok", "playlist": spotify_playlist_id, "results": results}

    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Playlist-Sync Fehler: %s", exc)
        raise HTTPException(status_code=500, detail=f"Playlist sync error: {exc}") from exc


@router.get("/status")
async def sync_status():
    """Return the availability of the orchestration dependencies."""

    try:
        status = {
            "spotify": worker.spotify.is_authenticated(),
            "soulseek": worker.soulseek.is_configured(),
            "plex": worker.plex.is_connected(),
            "beets": worker.beets.is_available(),
        }
        return {"status": "ok", "services": status}
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Status-Abfrage Fehler: %s", exc)
        raise HTTPException(status_code=500, detail=f"Status error: {exc}") from exc
