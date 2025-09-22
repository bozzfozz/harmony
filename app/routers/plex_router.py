"""Plex API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.plex_client import PlexClient
from app.dependencies import get_plex_client
from app.schemas import StatusResponse

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
def plex_status(client: PlexClient = Depends(get_plex_client)) -> StatusResponse:
    status = "connected" if client.is_connected() else "disconnected"
    return StatusResponse(status=status)


@router.get("/artists")
def list_artists(client: PlexClient = Depends(get_plex_client)) -> list:
    return client.get_all_artists()


@router.get("/artist/{artist_id}/albums")
def list_albums(artist_id: str, client: PlexClient = Depends(get_plex_client)) -> list:
    try:
        return client.get_albums_by_artist(artist_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Artist not found") from exc


@router.get("/album/{album_id}/tracks")
def list_tracks(album_id: str, client: PlexClient = Depends(get_plex_client)) -> list:
    try:
        return client.get_tracks_by_album(album_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Album not found") from exc
