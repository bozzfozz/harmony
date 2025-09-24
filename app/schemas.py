"""Pydantic schemas for request and response bodies."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, ConfigDict, computed_field


class StatusResponse(BaseModel):
    status: str
    artist_count: Optional[int] = None
    album_count: Optional[int] = None
    track_count: Optional[int] = None
    last_scan: Optional[datetime] = None


class SpotifySearchResponse(BaseModel):
    items: List[Dict[str, Any]]


class FollowedArtistsResponse(BaseModel):
    artists: List[Dict[str, Any]]


class ArtistReleasesResponse(BaseModel):
    artist_id: str
    releases: List[Dict[str, Any]]


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
    audio_features: Union[Dict[str, Any], List[Dict[str, Any]]]


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


class SoulseekSearchRequest(BaseModel):
    query: str


class SoulseekDownloadRequest(BaseModel):
    username: str = Field(..., description="Soulseek username hosting the files")
    files: List[Dict[str, Any]] = Field(..., description="List of files to download")


class SoulseekSearchResponse(BaseModel):
    """Response payload for Soulseek search results."""

    results: List[Any]
    raw: Optional[Dict[str, Any]] = None


class SoulseekDownloadResponse(BaseModel):
    """Response payload when a Soulseek download is queued."""

    status: str
    detail: Optional[Dict[str, Any]] = None


class SoulseekDownloadEntry(BaseModel):
    id: int
    filename: str
    state: str
    progress: float
    created_at: datetime
    updated_at: datetime
    priority: int = 0

    model_config = ConfigDict(from_attributes=True)


class SoulseekDownloadStatus(BaseModel):
    downloads: List[SoulseekDownloadEntry]


class DownloadEntryResponse(BaseModel):
    """Download information returned to API consumers."""

    id: int
    filename: str
    progress: float
    created_at: datetime
    updated_at: datetime
    priority: int = 0
    username: Optional[str] = None
    state: str = Field(exclude=True)

    model_config = ConfigDict(from_attributes=True)

    @computed_field(return_type=str)
    def status(self) -> str:
        """Expose the persisted state under the public ``status`` attribute."""

        return self.state


class DownloadListResponse(BaseModel):
    downloads: List[DownloadEntryResponse]


class SoulseekCancelResponse(BaseModel):
    cancelled: bool


class DownloadPriorityUpdate(BaseModel):
    priority: int


class MatchingRequest(BaseModel):
    spotify_track: Dict[str, Any]
    candidates: List[Dict[str, Any]]


class MatchingResponse(BaseModel):
    best_match: Optional[Dict[str, Any]]
    confidence: float


class AlbumMatchingRequest(BaseModel):
    spotify_album: Dict[str, Any]
    candidates: List[Dict[str, Any]]


class SettingsPayload(BaseModel):
    key: str
    value: Optional[str]


class SettingsResponse(BaseModel):
    settings: Dict[str, Optional[str]]
    updated_at: datetime


class SettingsHistoryEntry(BaseModel):
    key: str
    old_value: Optional[str]
    new_value: Optional[str]
    changed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SettingsHistoryResponse(BaseModel):
    history: List[SettingsHistoryEntry]


class ArtistPreferenceEntry(BaseModel):
    artist_id: str
    release_id: str
    selected: bool


class ArtistPreferencesPayload(BaseModel):
    preferences: List[ArtistPreferenceEntry] = Field(default_factory=list)


class ArtistPreferencesResponse(BaseModel):
    preferences: List[ArtistPreferenceEntry]
