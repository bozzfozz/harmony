"""Spotify API endpoints."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.spotify_client import SpotifyClient
from app.dependencies import get_db, get_spotify_client
from app.models import Playlist
from app.schemas import (
    ArtistReleasesResponse,
    AudioFeaturesResponse,
    FollowedArtistsResponse,
    PlaylistItemsResponse,
    PlaylistResponse,
    RecommendationsResponse,
    SavedTracksResponse,
    SpotifySearchResponse,
    StatusResponse,
    TrackDetailResponse,
    UserProfileResponse,
)

router = APIRouter()


class PlaylistTracksPayload(BaseModel):
    uris: List[str]


class PlaylistReorderPayload(BaseModel):
    range_start: int
    insert_before: int


class TrackIdsPayload(BaseModel):
    ids: List[str]


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


@router.get("/artists/followed", response_model=FollowedArtistsResponse)
def get_followed_artists(
    client: SpotifyClient = Depends(get_spotify_client),
) -> FollowedArtistsResponse:
    response = client.get_followed_artists()
    artists_section = response.get("artists") if isinstance(response, dict) else None
    items = []
    if isinstance(artists_section, dict):
        raw_items = artists_section.get("items") or []
        if isinstance(raw_items, list):
            items = [item for item in raw_items if isinstance(item, dict)]
    if not items and isinstance(response, dict):
        raw_items = response.get("items") or []
        if isinstance(raw_items, list):
            items = [item for item in raw_items if isinstance(item, dict)]
    return FollowedArtistsResponse(artists=items)


@router.get("/artist/{artist_id}/releases", response_model=ArtistReleasesResponse)
def get_artist_releases(
    artist_id: str,
    client: SpotifyClient = Depends(get_spotify_client),
) -> ArtistReleasesResponse:
    response = client.get_artist_releases(artist_id)
    raw_items = response.get("items") if isinstance(response, dict) else []
    releases = [item for item in raw_items or [] if isinstance(item, dict)]
    return ArtistReleasesResponse(artist_id=artist_id, releases=releases)


@router.get("/playlists", response_model=PlaylistResponse)
def list_playlists(db: Session = Depends(get_db)) -> PlaylistResponse:
    playlists = db.query(Playlist).order_by(Playlist.updated_at.desc()).all()
    return PlaylistResponse(playlists=playlists)


@router.get("/track/{track_id}", response_model=TrackDetailResponse)
def get_track_details(
    track_id: str,
    client: SpotifyClient = Depends(get_spotify_client),
) -> TrackDetailResponse:
    details = client.get_track_details(track_id)
    if not details:
        raise HTTPException(status_code=404, detail="Track not found")
    return TrackDetailResponse(track=details)


@router.get("/audio-features/{track_id}", response_model=AudioFeaturesResponse)
def get_audio_features(
    track_id: str,
    client: SpotifyClient = Depends(get_spotify_client),
) -> AudioFeaturesResponse:
    features = client.get_audio_features(track_id)
    if not features:
        raise HTTPException(status_code=404, detail="Audio features not found")
    return AudioFeaturesResponse(audio_features=features)


@router.get("/audio-features", response_model=AudioFeaturesResponse)
def get_multiple_audio_features(
    ids: str = Query(..., min_length=1),
    client: SpotifyClient = Depends(get_spotify_client),
) -> AudioFeaturesResponse:
    track_ids = [item.strip() for item in ids.split(",") if item.strip()]
    if not track_ids:
        raise HTTPException(status_code=400, detail="No track IDs provided")
    features = client.get_multiple_audio_features(track_ids)
    return AudioFeaturesResponse(audio_features=features.get("audio_features", []))


@router.get(
    "/playlists/{playlist_id}/tracks",
    response_model=PlaylistItemsResponse,
)
def get_playlist_items(
    playlist_id: str,
    limit: int = Query(100, ge=1, le=100),
    client: SpotifyClient = Depends(get_spotify_client),
) -> PlaylistItemsResponse:
    items = client.get_playlist_items(playlist_id, limit=limit)
    total = items.get("total")
    if total is None:
        total = items.get("tracks", {}).get("total")
    if total is None:
        total = len(items.get("items", []))
    return PlaylistItemsResponse(
        items=items.get("items", []),
        total=total,
    )


@router.post(
    "/playlists/{playlist_id}/tracks",
    response_model=StatusResponse,
)
def add_tracks_to_playlist(
    playlist_id: str,
    payload: PlaylistTracksPayload,
    client: SpotifyClient = Depends(get_spotify_client),
) -> StatusResponse:
    if not payload.uris:
        raise HTTPException(status_code=400, detail="No track URIs provided")
    client.add_tracks_to_playlist(playlist_id, payload.uris)
    return StatusResponse(status="tracks-added")


@router.delete(
    "/playlists/{playlist_id}/tracks",
    response_model=StatusResponse,
)
def remove_tracks_from_playlist(
    playlist_id: str,
    payload: PlaylistTracksPayload,
    client: SpotifyClient = Depends(get_spotify_client),
) -> StatusResponse:
    if not payload.uris:
        raise HTTPException(status_code=400, detail="No track URIs provided")
    client.remove_tracks_from_playlist(playlist_id, payload.uris)
    return StatusResponse(status="tracks-removed")


@router.put(
    "/playlists/{playlist_id}/reorder",
    response_model=StatusResponse,
)
def reorder_playlist(
    playlist_id: str,
    payload: PlaylistReorderPayload,
    client: SpotifyClient = Depends(get_spotify_client),
) -> StatusResponse:
    client.reorder_playlist_items(
        playlist_id,
        range_start=payload.range_start,
        insert_before=payload.insert_before,
    )
    return StatusResponse(status="playlist-reordered")


@router.get("/me/tracks", response_model=SavedTracksResponse)
def get_saved_tracks(
    limit: int = Query(20, ge=1, le=50),
    client: SpotifyClient = Depends(get_spotify_client),
) -> SavedTracksResponse:
    saved = client.get_saved_tracks(limit=limit)
    return SavedTracksResponse(items=saved.get("items", []), total=saved.get("total", len(saved.get("items", []))))


@router.put("/me/tracks", response_model=StatusResponse)
def save_tracks(
    payload: TrackIdsPayload,
    client: SpotifyClient = Depends(get_spotify_client),
) -> StatusResponse:
    if not payload.ids:
        raise HTTPException(status_code=400, detail="No track IDs provided")
    client.save_tracks(payload.ids)
    return StatusResponse(status="tracks-saved")


@router.delete("/me/tracks", response_model=StatusResponse)
def remove_saved_tracks(
    payload: TrackIdsPayload,
    client: SpotifyClient = Depends(get_spotify_client),
) -> StatusResponse:
    if not payload.ids:
        raise HTTPException(status_code=400, detail="No track IDs provided")
    client.remove_saved_tracks(payload.ids)
    return StatusResponse(status="tracks-removed")


@router.get("/me", response_model=UserProfileResponse)
def get_current_user(
    client: SpotifyClient = Depends(get_spotify_client),
) -> UserProfileResponse:
    profile = client.get_current_user()
    return UserProfileResponse(profile=profile)


@router.get("/me/top/tracks", response_model=SpotifySearchResponse)
def get_top_tracks(
    limit: int = Query(20, ge=1, le=50),
    client: SpotifyClient = Depends(get_spotify_client),
) -> SpotifySearchResponse:
    response = client.get_top_tracks(limit=limit)
    return SpotifySearchResponse(items=response.get("items", []))


@router.get("/me/top/artists", response_model=SpotifySearchResponse)
def get_top_artists(
    limit: int = Query(20, ge=1, le=50),
    client: SpotifyClient = Depends(get_spotify_client),
) -> SpotifySearchResponse:
    response = client.get_top_artists(limit=limit)
    return SpotifySearchResponse(items=response.get("items", []))


@router.get("/recommendations", response_model=RecommendationsResponse)
def get_recommendations(
    seed_tracks: Optional[str] = Query(None),
    seed_artists: Optional[str] = Query(None),
    seed_genres: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    client: SpotifyClient = Depends(get_spotify_client),
) -> RecommendationsResponse:
    def _split(value: Optional[str]) -> Optional[List[str]]:
        if value is None:
            return None
        result = [item.strip() for item in value.split(",") if item.strip()]
        return result or None

    response = client.get_recommendations(
        seed_tracks=_split(seed_tracks),
        seed_artists=_split(seed_artists),
        seed_genres=_split(seed_genres),
        limit=limit,
    )
    return RecommendationsResponse(
        tracks=response.get("tracks", []),
        seeds=response.get("seeds", []),
    )
