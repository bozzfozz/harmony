"""Spotify-specific schema definitions preserved for compatibility."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class SpotifySearchResponse(BaseModel):
    items: List[Dict[str, Any]]


class FollowedArtistsResponse(BaseModel):
    artists: List[Dict[str, Any]]


class ArtistReleasesResponse(BaseModel):
    artist_id: str
    releases: List[Dict[str, Any]]


class DiscographyAlbum(BaseModel):
    album: Dict[str, Any]
    tracks: List[Dict[str, Any]] = Field(default_factory=list)


class DiscographyResponse(BaseModel):
    artist_id: str
    albums: List[DiscographyAlbum] = Field(default_factory=list)


class PlaylistEntry(BaseModel):
    id: str
    name: str
    track_count: int
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlaylistResponse(BaseModel):
    playlists: List[PlaylistEntry]


class TrackDetailResponse(BaseModel):
    track: Dict[str, Any]


class AudioFeaturesResponse(BaseModel):
    audio_features: Dict[str, Any] | List[Dict[str, Any]]


class PlaylistItemsResponse(BaseModel):
    items: List[Dict[str, Any]]
    total: int


class SavedTracksResponse(BaseModel):
    items: List[Dict[str, Any]]
    total: int


class UserProfileResponse(BaseModel):
    profile: Dict[str, Any]


class RecommendationsResponse(BaseModel):
    tracks: List[Dict[str, Any]]
    seeds: List[Dict[str, Any]]


__all__ = [
    "ArtistReleasesResponse",
    "AudioFeaturesResponse",
    "DiscographyAlbum",
    "DiscographyResponse",
    "FollowedArtistsResponse",
    "PlaylistEntry",
    "PlaylistItemsResponse",
    "PlaylistResponse",
    "RecommendationsResponse",
    "SavedTracksResponse",
    "SpotifySearchResponse",
    "TrackDetailResponse",
    "UserProfileResponse",
]
