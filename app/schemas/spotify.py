"""Spotify-specific schema definitions preserved for compatibility."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SpotifySearchResponse(BaseModel):
    items: list[dict[str, Any]]


class FollowedArtistsResponse(BaseModel):
    artists: list[dict[str, Any]]


class ArtistReleasesResponse(BaseModel):
    artist_id: str
    releases: list[dict[str, Any]]


class DiscographyAlbum(BaseModel):
    album: dict[str, Any]
    tracks: list[dict[str, Any]] = Field(default_factory=list)


class DiscographyResponse(BaseModel):
    artist_id: str
    albums: list[DiscographyAlbum] = Field(default_factory=list)


class PlaylistEntry(BaseModel):
    id: str
    name: str
    track_count: int
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlaylistResponse(BaseModel):
    playlists: list[PlaylistEntry]


class TrackDetailResponse(BaseModel):
    track: dict[str, Any]


class AudioFeaturesResponse(BaseModel):
    audio_features: dict[str, Any] | list[dict[str, Any]]


class PlaylistItemsResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


class SavedTracksResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


class UserProfileResponse(BaseModel):
    profile: dict[str, Any]


class RecommendationsResponse(BaseModel):
    tracks: list[dict[str, Any]]
    seeds: list[dict[str, Any]]


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
