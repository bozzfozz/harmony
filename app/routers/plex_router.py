from fastapi import APIRouter, HTTPException

from app.core.plex_client import PlexClient
from app.utils.logging_config import get_logger

router = APIRouter()
logger = get_logger("plex_router")
client = PlexClient()


@router.get("/artists")
async def get_artists() -> dict:
    try:
        return {"artists": client.get_all_artists()}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to fetch artists: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
