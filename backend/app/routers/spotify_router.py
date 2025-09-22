"""FastAPI routes exposing Spotify search and metadata."""

from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.utils.logging_config import get_logger
from backend.app.core.spotify_client import SpotifyClient


logger = get_logger("spotify_router")


class TrackSummary(BaseModel):
    id: str | None = Field(default=None, description="Spotify track identifier")
    name: str | None = Field(default=None, description="Track title")
    artists: List[str] = Field(default_factory=list, description="Artists on the track")
    album: str | None = Field(default=None, description="Album title")
    duration_ms: int | None = Field(default=None, description="Duration in milliseconds")
    popularity: int | None = Field(default=None, description="Spotify popularity score")


class ArtistSummary(BaseModel):
    id: str | None = None
    name: str | None = None
    genres: List[str] = Field(default_factory=list)
    followers: int | None = None


class AlbumSummary(BaseModel):
    id: str | None = None
    name: str | None = None
    artists: List[str] = Field(default_factory=list)
    release_date: str | None = None
    total_tracks: int | None = None


class PlaylistSummary(BaseModel):
    id: str | None = None
    name: str | None = None
    owner: str | None = None
    tracks: int | None = Field(default=None, description="Number of tracks")


class AlbumDetail(BaseModel):
    id: str | None = None
    name: str | None = None
    release_date: str | None = None


class TrackDetails(BaseModel):
    id: str
    name: str
    artists: List[str]
    album: AlbumDetail | None = None
    duration_ms: int | None = None
    popularity: int | None = None
    preview_url: str | None = None
    uri: str | None = None


class StatusResponse(BaseModel):
    authenticated: bool


class TrackSearchResponse(BaseModel):
    tracks: List[TrackSummary]


class ArtistSearchResponse(BaseModel):
    artists: List[ArtistSummary]


class AlbumSearchResponse(BaseModel):
    albums: List[AlbumSummary]


class PlaylistResponse(BaseModel):
    playlists: List[PlaylistSummary]


router = APIRouter(prefix="/spotify", tags=["Spotify"])

spotify_client = SpotifyClient()


def _handle_spotify_error(action: str, exc: Exception) -> HTTPException:
    logger.error("Spotify %s failed: %s", action, exc)
    return HTTPException(status_code=502, detail=f"Spotify {action} failed")


@router.get("/status", response_model=StatusResponse)
def spotify_status() -> StatusResponse:
    try:
        authenticated = spotify_client.is_authenticated()
    except Exception as exc:  # pragma: no cover - defensive safety net
        logger.error("Unable to determine Spotify authentication state: %s", exc)
        raise HTTPException(status_code=503, detail="Spotify status unavailable") from exc

    return StatusResponse(authenticated=bool(authenticated))


@router.get("/search/tracks", response_model=TrackSearchResponse)
def search_tracks(query: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)) -> TrackSearchResponse:
    try:
        results = spotify_client.search_tracks(query, limit=limit)
    except Exception as exc:
        raise _handle_spotify_error("track search", exc) from exc

    return TrackSearchResponse(tracks=[TrackSummary(**item) for item in results])


@router.get("/search/artists", response_model=ArtistSearchResponse)
def search_artists(query: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)) -> ArtistSearchResponse:
    try:
        results = spotify_client.search_artists(query, limit=limit)
    except Exception as exc:
        raise _handle_spotify_error("artist search", exc) from exc

    return ArtistSearchResponse(artists=[ArtistSummary(**item) for item in results])


@router.get("/search/albums", response_model=AlbumSearchResponse)
def search_albums(query: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)) -> AlbumSearchResponse:
    try:
        results = spotify_client.search_albums(query, limit=limit)
    except Exception as exc:
        raise _handle_spotify_error("album search", exc) from exc

    return AlbumSearchResponse(albums=[AlbumSummary(**item) for item in results])


@router.get("/playlists", response_model=PlaylistResponse)
def list_playlists() -> PlaylistResponse:
    try:
        playlists = spotify_client.get_user_playlists()
    except Exception as exc:
        raise _handle_spotify_error("playlist retrieval", exc) from exc

    return PlaylistResponse(playlists=[PlaylistSummary(**item) for item in playlists])


@router.get("/track/{track_id}", response_model=TrackDetails)
def track_details(track_id: str) -> TrackDetails:
    try:
        details = spotify_client.get_track_details(track_id)
    except Exception as exc:
        raise _handle_spotify_error("track lookup", exc) from exc

    if not details:
        raise HTTPException(status_code=404, detail="Spotify track not found")

    return TrackDetails(**details)


__all__ = ["router"]

