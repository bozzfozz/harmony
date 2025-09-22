"""Spotify API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.spotify_client import SpotifyClient
from app.dependencies import get_spotify_client
from app.schemas import PlaylistResponse, SpotifySearchResponse, StatusResponse, TrackDetailResponse

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
def spotify_status(client: SpotifyClient = Depends(get_spotify_client)) -> StatusResponse:
    status = "connected" if client.is_authenticated() else "unauthenticated"
    return StatusResponse(status=status)


@router.get("/search/tracks", response_model=SpotifySearchResponse)
def search_tracks(
    query: str = Query(..., min_length=1),
    client: SpotifyClient = Depends(get_spotify_client),
) -> SpotifySearchResponse:
    response = client.search_tracks(query)
    items = response.get("tracks", {}).get("items", [])
    return SpotifySearchResponse(items=items)


@router.get("/search/artists", response_model=SpotifySearchResponse)
def search_artists(
    query: str = Query(..., min_length=1),
    client: SpotifyClient = Depends(get_spotify_client),
) -> SpotifySearchResponse:
    response = client.search_artists(query)
    items = response.get("artists", {}).get("items", [])
    return SpotifySearchResponse(items=items)


@router.get("/search/albums", response_model=SpotifySearchResponse)
def search_albums(
    query: str = Query(..., min_length=1),
    client: SpotifyClient = Depends(get_spotify_client),
) -> SpotifySearchResponse:
    response = client.search_albums(query)
    items = response.get("albums", {}).get("items", [])
    return SpotifySearchResponse(items=items)


@router.get("/playlists", response_model=PlaylistResponse)
def list_playlists(client: SpotifyClient = Depends(get_spotify_client)) -> PlaylistResponse:
    response = client.get_user_playlists()
    items = response.get("items", [])
    return PlaylistResponse(playlists=items)


@router.get("/track/{track_id}", response_model=TrackDetailResponse)
def get_track_details(
    track_id: str,
    client: SpotifyClient = Depends(get_spotify_client),
) -> TrackDetailResponse:
    details = client.get_track_details(track_id)
    if not details:
        raise HTTPException(status_code=404, detail="Track not found")
    return TrackDetailResponse(track=details)
