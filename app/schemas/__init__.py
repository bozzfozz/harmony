"""Pydantic schemas for request and response bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import (BaseModel, ConfigDict, Field, computed_field,
                      field_validator, model_validator)


class StatusResponse(BaseModel):
    status: str
    artist_count: Optional[int] = None
    album_count: Optional[int] = None
    track_count: Optional[int] = None
    last_scan: Optional[datetime] = None
    connections: Optional[Dict[str, str]] = None


class ServiceHealthResponse(BaseModel):
    service: str
    status: Literal["ok", "fail", "disabled"]
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


class DownloadFileRequest(BaseModel):
    """Input payload for an individual download request."""

    filename: Optional[str] = Field(
        None, description="Resolved filename that should be stored for the download"
    )
    name: Optional[str] = Field(
        None, description="Original filename reported by the client (fallback field)"
    )
    priority: Optional[int] = Field(
        None, description="Explicit priority override for this download"
    )
    source: Optional[str] = Field(
        None, description="Origin of the download request, e.g. spotify_saved"
    )

    model_config = ConfigDict(extra="allow")

    @field_validator("filename", "name")
    @classmethod
    def _normalise_filename(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _ensure_identifier(self) -> "DownloadFileRequest":
        if self.filename or self.name:
            return self
        raise ValueError("filename or name must be provided")

    @property
    def resolved_filename(self) -> str:
        return self.filename or self.name or "unknown"

    def to_payload(self) -> Dict[str, Any]:
        payload = self.model_dump(by_alias=True, exclude_none=True)
        payload.setdefault("filename", self.resolved_filename)
        return payload


class SoulseekDownloadRequest(BaseModel):
    username: str = Field(..., description="Soulseek username hosting the files")
    files: List[DownloadFileRequest] = Field(..., description="List of files to download")

    @field_validator("username")
    @classmethod
    def _ensure_username(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("username must not be empty")
        return stripped


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


_CANONICAL_DOWNLOAD_STATE_MAP = {
    "queued": "pending",
    "downloading": "in_progress",
    "completed": "completed",
    "failed": "failed",
    "dead_letter": "dead_letter",
    "cancelled": "failed",
}

_REQUEUE_PROHIBITED_DB_STATES = frozenset({"dead_letter", "queued", "downloading"})


def _canonical_download_state(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return _CANONICAL_DOWNLOAD_STATE_MAP.get(normalized, normalized or "pending")


def _default_retryable_states() -> List[str]:
    allowed_db_states = set(_CANONICAL_DOWNLOAD_STATE_MAP.keys()) - set(
        _REQUEUE_PROHIBITED_DB_STATES
    )
    canonical_states = {_canonical_download_state(state) for state in allowed_db_states}
    return sorted(canonical_states)


SOULSEEK_RETRYABLE_STATES: tuple[str, ...] = tuple(_default_retryable_states())


def _retryable_states_default() -> List[str]:
    return list(SOULSEEK_RETRYABLE_STATES)


class SoulseekDownloadEntry(BaseModel):
    id: int
    filename: str
    db_state: str = Field(alias="state", exclude=True)
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
    retry_count: int = 0
    next_retry_at: Optional[datetime] = None
    last_error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field(return_type=str, alias="state")
    def state(self) -> str:
        return _canonical_download_state(self.db_state)


class SoulseekDownloadStatus(BaseModel):
    downloads: List[SoulseekDownloadEntry]
    retryable_states: List[str] = Field(default_factory=_retryable_states_default)


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
    db_state: str = Field(alias="state", exclude=True)
    retry_count: int = 0
    next_retry_at: Optional[datetime] = None
    last_error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field(return_type=str, alias="state")
    def state(self) -> str:
        """Expose canonical download state names."""

        return _canonical_download_state(self.db_state)

    @computed_field(return_type=str)
    def status(self) -> str:
        """Provide backwards compatible ``status`` attribute."""

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
