"""Pydantic schemas for request and response bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, ConfigDict, computed_field


class StatusResponse(BaseModel):
    status: str
    artist_count: Optional[int] = None
    album_count: Optional[int] = None
    track_count: Optional[int] = None
    last_scan: Optional[datetime] = None
    connections: Optional[Dict[str, str]] = None


class ServiceHealthResponse(BaseModel):
    service: str
    status: Literal["ok", "fail"]
    missing: List[str] = Field(default_factory=list)
    optional_missing: List[str] = Field(default_factory=list)


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


class DiscographyDownloadRequest(BaseModel):
    artist_id: str
    artist_name: Optional[str] = None


class DiscographyJobResponse(BaseModel):
    job_id: int
    status: str


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
    organized_path: Optional[str] = None
    genre: Optional[str] = None
    composer: Optional[str] = None
    producer: Optional[str] = None
    isrc: Optional[str] = None
    copyright: Optional[str] = None
    artwork_url: Optional[str] = None
    artwork_path: Optional[str] = None
    artwork_status: Optional[str] = None
    has_artwork: Optional[bool] = None
    spotify_track_id: Optional[str] = None
    spotify_album_id: Optional[str] = None
    lyrics_status: Optional[str] = None
    lyrics_path: Optional[str] = None
    has_lyrics: Optional[bool] = None

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
    organized_path: Optional[str] = None
    genre: Optional[str] = None
    composer: Optional[str] = None
    producer: Optional[str] = None
    isrc: Optional[str] = None
    copyright: Optional[str] = None
    artwork_url: Optional[str] = None
    artwork_path: Optional[str] = None
    artwork_status: Optional[str] = None
    has_artwork: Optional[bool] = None
    spotify_track_id: Optional[str] = None
    spotify_album_id: Optional[str] = None
    lyrics_status: Optional[str] = None
    lyrics_path: Optional[str] = None
    has_lyrics: Optional[bool] = None
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


class DownloadMetadataResponse(BaseModel):
    id: int
    filename: str
    genre: Optional[str] = None
    composer: Optional[str] = None
    producer: Optional[str] = None
    isrc: Optional[str] = None
    copyright: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DownloadPriorityUpdate(BaseModel):
    priority: int


class MatchingRequest(BaseModel):
    spotify_track: Dict[str, Any]
    candidates: List[Dict[str, Any]]


class MatchingResponse(BaseModel):
    best_match: Optional[Dict[str, Any]]
    confidence: float


class DiscographyMatchingRequest(BaseModel):
    artist_id: str
    albums: List[Dict[str, Any]] = Field(default_factory=list)
    plex_items: List[Dict[str, Any]] = Field(default_factory=list)


class DiscographyMissingAlbum(BaseModel):
    album: Dict[str, Any]
    missing_tracks: List[Dict[str, Any]] = Field(default_factory=list)


class DiscographyMissingTrack(BaseModel):
    album: Dict[str, Any]
    track: Dict[str, Any]


class DiscographyMatchingResponse(BaseModel):
    missing_albums: List[DiscographyMissingAlbum] = Field(default_factory=list)
    missing_tracks: List[DiscographyMissingTrack] = Field(default_factory=list)


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
