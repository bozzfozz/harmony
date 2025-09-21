from typing import List

from fastapi import APIRouter, HTTPException

from app.core.matching_engine import MusicMatchingEngine
from app.utils.logging_config import get_logger

router = APIRouter()
logger = get_logger("matching_router")
engine = MusicMatchingEngine()


@router.post("/match")
async def match_track(spotify_track: dict, plex_candidates: List[dict]) -> dict:
    try:
        from app.core.spotify_client import Track
        from app.core.plex_client import PlexTrackInfo

        spotify_obj = Track.from_spotify_track(spotify_track)
        plex_objs = [PlexTrackInfo(**candidate) for candidate in plex_candidates]
        match = engine.find_best_match(spotify_obj, plex_objs)
        return {"match": match.__dict__ if match else None}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Matching failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
