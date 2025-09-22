from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.plex_client import PlexClient
from app.utils.logging_config import get_logger

router = APIRouter()
logger = get_logger("plex_router")
plex_client = PlexClient()


class PlexLibraryResponse(BaseModel):
    libraries: List[str]


class PlexTrack(BaseModel):
    title: str
    artist: str
    album: Optional[str]
    duration: Optional[int]


class PlexTrackResponse(BaseModel):
    tracks: List[PlexTrack]


class PlexAlbum(BaseModel):
    title: str
    artist: str
    year: Optional[int]
    track_count: int


class PlexAlbumResponse(BaseModel):
    albums: List[PlexAlbum]


@router.get("/status")
async def status() -> dict:
    """Check if Plex client is connected and music library is available."""
    try:
        ok = plex_client.is_connected()
        return {"plex_connected": ok}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Plex status check failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/libraries", response_model=PlexLibraryResponse)
async def list_libraries() -> PlexLibraryResponse:
    """List available Plex libraries."""
    try:
        libs = plex_client.list_libraries()
        return PlexLibraryResponse(libraries=libs)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Error fetching Plex libraries: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/search/tracks", response_model=PlexTrackResponse)
async def search_tracks(query: str = Query(..., min_length=2)) -> PlexTrackResponse:
    """Search tracks in Plex music library."""
    try:
        results = plex_client.search_tracks(query)
        tracks = [
            PlexTrack(
                title=result.title,
                artist=result.artist,
                album=getattr(result, "album", None),
                duration=getattr(result, "duration", None),
            )
            for result in results
        ]
        return PlexTrackResponse(tracks=tracks)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Error searching Plex tracks: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/search/albums", response_model=PlexAlbumResponse)
async def search_albums(query: str = Query(..., min_length=2)) -> PlexAlbumResponse:
    """Search albums in Plex music library."""
    try:
        results = plex_client.search_albums(query)
        albums = [
            PlexAlbum(
                title=result.title,
                artist=result.artist,
                year=getattr(result, "year", None),
                track_count=getattr(result, "track_count", 0),
            )
            for result in results
        ]
        return PlexAlbumResponse(albums=albums)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Error searching Plex albums: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/artists")
async def get_artists() -> dict:
    try:
        return {"artists": plex_client.get_all_artists()}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to fetch artists: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
