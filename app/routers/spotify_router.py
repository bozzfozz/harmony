"""Core Spotify router delegating to :mod:`SpotifyDomainService`."""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.dependencies import (
    get_app_config,
    get_db,
    get_soulseek_client,
    get_spotify_client,
)
from app.schemas import (
    ArtistReleasesResponse,
    AudioFeaturesResponse,
    DiscographyResponse,
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
from app.services.spotify_domain_service import PlaylistItemsResult, SpotifyDomainService

router = APIRouter()


class PlaylistTracksPayload(BaseModel):
    uris: List[str]


class PlaylistReorderPayload(BaseModel):
    range_start: int
    insert_before: int


class TrackIdsPayload(BaseModel):
    ids: List[str]


class SpotifyModeResponse(BaseModel):
    mode: Literal["FREE", "PRO"]


class SpotifyModePayload(BaseModel):
    mode: Literal["FREE", "PRO"]


def _get_spotify_service(
    request: Request,
    config=Depends(get_app_config),
    spotify_client: SpotifyClient = Depends(get_spotify_client),
    soulseek_client: SoulseekClient = Depends(get_soulseek_client),
) -> SpotifyDomainService:
    return SpotifyDomainService(
        config=config,
        spotify_client=spotify_client,
        soulseek_client=soulseek_client,
        app_state=request.app.state,
    )


@router.get("/mode", response_model=SpotifyModeResponse)
def get_spotify_mode(
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifyModeResponse:
    return SpotifyModeResponse(mode=service.get_mode())


@router.post("/mode")
def update_spotify_mode(
    payload: SpotifyModePayload,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> dict[str, bool]:
    service.update_mode(payload.mode)
    return {"ok": True}


@router.get("/status", response_model=StatusResponse)
def spotify_status(
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> StatusResponse:
    return StatusResponse(status=service.get_status())


@router.get("/search/tracks", response_model=SpotifySearchResponse)
def search_tracks(
    query: str = Query(..., min_length=1),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifySearchResponse:
    items = service.search_tracks(query)
    return SpotifySearchResponse(items=list(items))


@router.get("/search/artists", response_model=SpotifySearchResponse)
def search_artists(
    query: str = Query(..., min_length=1),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifySearchResponse:
    items = service.search_artists(query)
    return SpotifySearchResponse(items=list(items))


@router.get("/search/albums", response_model=SpotifySearchResponse)
def search_albums(
    query: str = Query(..., min_length=1),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifySearchResponse:
    items = service.search_albums(query)
    return SpotifySearchResponse(items=list(items))


@router.get("/artists/followed", response_model=FollowedArtistsResponse)
def get_followed_artists(
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> FollowedArtistsResponse:
    return FollowedArtistsResponse(artists=list(service.get_followed_artists()))


@router.get("/artist/{artist_id}/releases", response_model=ArtistReleasesResponse)
def get_artist_releases(
    artist_id: str,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> ArtistReleasesResponse:
    releases = service.get_artist_releases(artist_id)
    return ArtistReleasesResponse(artist_id=artist_id, releases=list(releases))


@router.get("/artist/{artist_id}/discography", response_model=DiscographyResponse)
def get_artist_discography(
    artist_id: str,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> DiscographyResponse:
    albums = service.get_artist_discography(artist_id)
    return DiscographyResponse(artist_id=artist_id, albums=list(albums))


@router.get("/playlists", response_model=PlaylistResponse)
def list_playlists(
    db: Session = Depends(get_db),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> PlaylistResponse:
    playlists = service.list_playlists(db)
    return PlaylistResponse(playlists=list(playlists))


@router.get(
    "/playlists/{playlist_id}/tracks",
    response_model=PlaylistItemsResponse,
)
def get_playlist_items(
    playlist_id: str,
    limit: int = Query(100, ge=1, le=100),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> PlaylistItemsResponse:
    result: PlaylistItemsResult = service.get_playlist_items(playlist_id, limit=limit)
    return PlaylistItemsResponse(items=list(result.items), total=result.total)


@router.post(
    "/playlists/{playlist_id}/tracks",
    response_model=StatusResponse,
)
def add_tracks_to_playlist(
    playlist_id: str,
    payload: PlaylistTracksPayload,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> StatusResponse:
    if not payload.uris:
        raise HTTPException(status_code=400, detail="No track URIs provided")
    service.add_tracks_to_playlist(playlist_id, payload.uris)
    return StatusResponse(status="tracks-added")


@router.delete(
    "/playlists/{playlist_id}/tracks",
    response_model=StatusResponse,
)
def remove_tracks_from_playlist(
    playlist_id: str,
    payload: PlaylistTracksPayload,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> StatusResponse:
    if not payload.uris:
        raise HTTPException(status_code=400, detail="No track URIs provided")
    service.remove_tracks_from_playlist(playlist_id, payload.uris)
    return StatusResponse(status="tracks-removed")


@router.put(
    "/playlists/{playlist_id}/reorder",
    response_model=StatusResponse,
)
def reorder_playlist(
    playlist_id: str,
    payload: PlaylistReorderPayload,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> StatusResponse:
    service.reorder_playlist(
        playlist_id,
        range_start=payload.range_start,
        insert_before=payload.insert_before,
    )
    return StatusResponse(status="playlist-reordered")


@router.get("/track/{track_id}", response_model=TrackDetailResponse)
def get_track_details(
    track_id: str,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> TrackDetailResponse:
    details = service.get_track_details(track_id)
    if not details:
        raise HTTPException(status_code=404, detail="Track not found")
    return TrackDetailResponse(track=details)


@router.get("/audio-features/{track_id}", response_model=AudioFeaturesResponse)
def get_audio_features(
    track_id: str,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> AudioFeaturesResponse:
    features = service.get_audio_features(track_id)
    if not features:
        raise HTTPException(status_code=404, detail="Audio features not found")
    return AudioFeaturesResponse(audio_features=features)


@router.get("/audio-features", response_model=AudioFeaturesResponse)
def get_multiple_audio_features(
    ids: str = Query(..., min_length=1),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> AudioFeaturesResponse:
    track_ids = [item.strip() for item in ids.split(",") if item.strip()]
    if not track_ids:
        raise HTTPException(status_code=400, detail="No track IDs provided")
    features = service.get_multiple_audio_features(track_ids)
    return AudioFeaturesResponse(audio_features=list(features))


@router.get("/me/tracks", response_model=SavedTracksResponse)
def get_saved_tracks(
    limit: int = Query(20, ge=1, le=50),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SavedTracksResponse:
    saved = service.get_saved_tracks(limit=limit)
    return SavedTracksResponse(items=list(saved["items"]), total=saved["total"])


@router.put("/me/tracks", response_model=StatusResponse)
def save_tracks(
    payload: TrackIdsPayload,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> StatusResponse:
    if not payload.ids:
        raise HTTPException(status_code=400, detail="No track IDs provided")
    service.save_tracks(payload.ids)
    return StatusResponse(status="tracks-saved")


@router.delete("/me/tracks", response_model=StatusResponse)
def remove_saved_tracks(
    payload: TrackIdsPayload,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> StatusResponse:
    if not payload.ids:
        raise HTTPException(status_code=400, detail="No track IDs provided")
    service.remove_saved_tracks(payload.ids)
    return StatusResponse(status="tracks-removed")


@router.get("/me", response_model=UserProfileResponse)
def get_current_user(
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> UserProfileResponse:
    profile = service.get_current_user() or {}
    return UserProfileResponse(profile=profile)


@router.get("/me/top/tracks", response_model=SpotifySearchResponse)
def get_top_tracks(
    limit: int = Query(20, ge=1, le=50),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifySearchResponse:
    items = service.get_top_tracks(limit=limit)
    return SpotifySearchResponse(items=list(items))


@router.get("/me/top/artists", response_model=SpotifySearchResponse)
def get_top_artists(
    limit: int = Query(20, ge=1, le=50),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifySearchResponse:
    items = service.get_top_artists(limit=limit)
    return SpotifySearchResponse(items=list(items))


@router.get("/recommendations", response_model=RecommendationsResponse)
def get_recommendations(
    seed_tracks: Optional[str] = Query(None),
    seed_artists: Optional[str] = Query(None),
    seed_genres: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> RecommendationsResponse:
    def _split(value: Optional[str]) -> Optional[list[str]]:
        if value is None:
            return None
        result = [item.strip() for item in value.split(",") if item.strip()]
        return result or None

    payload = service.get_recommendations(
        seed_tracks=_split(seed_tracks),
        seed_artists=_split(seed_artists),
        seed_genres=_split(seed_genres),
        limit=limit,
    )
    return RecommendationsResponse(
        tracks=list(payload["tracks"]),
        seeds=list(payload["seeds"]),
    )


__all__ = ["router"]
