from dataclasses import asdict
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from app.core.soulseek_client import SoulseekClient, TrackResult
from app.utils.logging_config import get_logger


logger = get_logger("soulseek_router")
router = APIRouter()
client = SoulseekClient()


def _serialise_tracks(tracks: List[TrackResult]) -> List[Dict[str, Any]]:
    """Convert dataclass track results into dictionaries for the API response."""

    return [asdict(track) for track in tracks]


async def _search_tracks_internal(query: str, timeout: int) -> Dict[str, Any]:
    try:
        tracks = await client.search(query, timeout=timeout)
        serialised = _serialise_tracks(tracks)
        return {"results": serialised, "count": len(serialised)}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Search failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/search")
async def search_tracks(
    query: str = Query(..., description="Track or artist to search"),
    timeout: int = Query(30, ge=5, le=60, description="Search timeout in seconds"),
) -> Dict[str, Any]:
    return await _search_tracks_internal(query, timeout)


@router.get("/search/tracks")
async def search_tracks_explicit(
    query: str = Query(..., description="Track or artist to search"),
    timeout: int = Query(30, ge=5, le=60, description="Search timeout in seconds"),
) -> Dict[str, Any]:
    return await _search_tracks_internal(query, timeout)


@router.post("/download")
async def download(username: str, filename: str, size: int = 0) -> dict:
    try:
        started = await client.download(username, filename, size)
        if not started:
            raise HTTPException(status_code=502, detail="Failed to schedule download")
        return {"status": "started", "filename": filename}
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Download failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
