from fastapi import APIRouter, HTTPException, Query

from app.core.spotify_client import SpotifyClient
from app.utils.logging_config import get_logger

router = APIRouter()
logger = get_logger("spotify_router")
client = SpotifyClient()


@router.get("/playlists")
async def get_playlists() -> dict:
    try:
        playlists = client.get_user_playlists_metadata_only()
        return {"playlists": [playlist.__dict__ for playlist in playlists]}
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Playlist fetch failed: %s", exc, exc_info=exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/search")
async def search_tracks(query: str = Query(...)) -> dict:
    try:
        results = client.search_tracks(query)
        return {"tracks": [track.__dict__ for track in results]}
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Spotify search failed: %s", exc, exc_info=exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
