"""FastAPI router exposing Soulseek search and download endpoints."""
from __future__ import annotations

from typing import Iterable, List

from fastapi import APIRouter, HTTPException

from core.soulseek_client import SoulseekClient, TrackResult
from utils.logging_config import get_logger

logger = get_logger("soulseek_router")

router = APIRouter()
_client = SoulseekClient()


def _serialize_track(result: TrackResult | dict | object) -> dict:
    """Convert a track result into a serialisable dictionary."""

    if isinstance(result, TrackResult):
        return result.to_dict()

    if isinstance(result, dict):
        return result

    if hasattr(result, "dict") and callable(result.dict):
        return result.dict()  # type: ignore[misc]

    if hasattr(result, "model_dump") and callable(result.model_dump):
        return result.model_dump()  # type: ignore[misc]

    return {
        key: value
        for key, value in vars(result).items()
        if not key.startswith("_")
    }


def _serialize_results(results: Iterable[TrackResult | dict | object]) -> List[dict]:
    return [_serialize_track(item) for item in results]


@router.get("/search", response_model=List[dict])
async def search_tracks(query: str):
    """Search for tracks on the Soulseek network."""

    try:
        results = await _client.search(query)
        return _serialize_results(results)
    except Exception as exc:  # pragma: no cover - defensive safeguard
        logger.error("Search failed: %s", exc)
        raise HTTPException(status_code=500, detail="Search failed") from exc


@router.post("/download")
async def download_track(username: str, filename: str, size: int = 0):
    """Start downloading a track from a Soulseek user."""

    try:
        success = await _client.download(username, filename, size)
        if not success:
            raise HTTPException(status_code=400, detail="Download failed")

        return {"status": "ok", "filename": filename}
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive safeguard
        logger.error("Download failed: %s", exc)
        raise HTTPException(status_code=500, detail="Download failed") from exc
