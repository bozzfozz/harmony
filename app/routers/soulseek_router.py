from fastapi import APIRouter, HTTPException, Query

from app.core.soulseek_client import SoulseekClient
from app.utils.logging_config import get_logger


router = APIRouter()
logger = get_logger("soulseek_router")
client = SoulseekClient()


@router.get("/search")
async def search_tracks(
    query: str = Query(..., description="Track or artist to search"),
    timeout: int = Query(30, ge=5, le=60, description="Search timeout in seconds"),
) -> dict:
    try:
        tracks = await client.search(query, timeout=timeout)
        return {"results": [track.__dict__ for track in tracks], "count": len(tracks)}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Search failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/download")
async def download(username: str, filename: str, size: int = 0) -> dict:
    try:
        started = await client.download(username, filename, size)
        if not started:
            raise HTTPException(status_code=502, detail="Failed to schedule download")
        return {"status": "started"}
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Download failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
