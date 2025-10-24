"""Pydantic schemas for request and response bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


class StatusResponse(BaseModel):
    status: str
    artist_count: int | None = None
    album_count: int | None = None
    track_count: int | None = None
    last_scan: datetime | None = None
    connections: dict[str, str] | None = None


class ServiceHealthResponse(BaseModel):
    service: str
    status: Literal["ok", "fail", "disabled"]
    missing: list[str] = Field(default_factory=list)
    optional_missing: list[str] = Field(default_factory=list)


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


class SoulseekSearchRequest(BaseModel):
    query: str
    min_bitrate: int | None = Field(
        None,
        ge=0,
        description="Minimum bitrate filter in kbps",
    )
    preferred_formats: list[str] | None = Field(
        default=None,
        min_length=1,
        description="Preferred audio formats ranked from most to least desired",
    )

    @field_validator("query")
    @classmethod
    def _ensure_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be empty")
        return stripped

    @field_validator("preferred_formats")
    @classmethod
    def _validate_formats(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        for entry in value:
            if entry is None:
                raise ValueError("preferred_formats entries must be non-empty strings")
            stripped = entry.strip()
            if not stripped:
                raise ValueError("preferred_formats entries must be non-empty strings")
            cleaned.append(stripped)
        return cleaned


class DownloadFileRequest(BaseModel):
    """Input payload for an individual download request."""

    filename: str | None = Field(
        None, description="Resolved filename that should be stored for the download"
    )
    name: str | None = Field(
        None, description="Original filename reported by the client (fallback field)"
    )
    priority: int | None = Field(None, description="Explicit priority override for this download")
    source: str | None = Field(
        None, description="Origin of the download request, e.g. spotify_saved"
    )

    model_config = ConfigDict(extra="allow")

    @field_validator("filename", "name")
    @classmethod
    def _normalise_filename(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _ensure_identifier(self) -> DownloadFileRequest:
        if self.filename or self.name:
            return self
        raise ValueError("filename or name must be provided")

    @property
    def resolved_filename(self) -> str:
        return self.filename or self.name or "unknown"

    def to_payload(self) -> dict[str, Any]:
        payload = self.model_dump(by_alias=True, exclude_none=True)
        payload.setdefault("filename", self.resolved_filename)
        return payload


class SoulseekDownloadRequest(BaseModel):
    username: str = Field(..., description="Soulseek username hosting the files")
    files: list[DownloadFileRequest] = Field(..., description="List of files to download")

    @field_validator("username")
    @classmethod
    def _ensure_username(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("username must not be empty")
        return stripped


class HdmItemRequest(BaseModel):
    artist: str = Field(..., description="Artist name for the requested download")
    title: str = Field(..., description="Track title for the requested download")
    album: str | None = Field(None, description="Album name associated with the track")
    isrc: str | None = Field(None, description="ISRC identifier if available")
    duration_seconds: float | None = Field(
        None, ge=0.0, description="Expected track duration in seconds"
    )
    bitrate: int | None = Field(None, ge=0, description="Expected bitrate in kbps")
    priority: int | None = Field(None, ge=0, description="Priority override for the item")
    dedupe_key: str | None = Field(
        None, description="Optional idempotency key for the individual item"
    )
    requested_by: str | None = Field(
        None, description="Requesting user if different from the batch requester"
    )

    @field_validator("artist", "title")
    @classmethod
    def _ensure_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped


class HdmBatchRequest(BaseModel):
    requested_by: str = Field(..., description="Identifier for the requesting user")
    items: list[HdmItemRequest] = Field(
        ..., min_length=1, description="Items to submit to the Harmony Download Manager"
    )
    batch_id: str | None = Field(None, description="Optional client supplied batch identifier")
    priority: int | None = Field(
        None, ge=0, description="Priority to apply to all items if provided"
    )
    dedupe_key: str | None = Field(None, description="Optional idempotency key for the batch")

    @field_validator("requested_by")
    @classmethod
    def _ensure_requested_by(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("requested_by must not be empty")
        return stripped


class HdmSubmissionResponse(BaseModel):
    batch_id: str
    items_total: int
    requested_by: str


# Backward compatibility aliases (planned removal in v1.2.0)
DownloadFlowItemRequest = HdmItemRequest
DownloadFlowBatchRequest = HdmBatchRequest
DownloadFlowSubmissionResponse = HdmSubmissionResponse


class DiscographyDownloadRequest(BaseModel):
    artist_id: str
    artist_name: str | None = None


class DiscographyJobResponse(BaseModel):
    job_id: int
    status: str


class SoulseekSearchResponse(BaseModel):
    """Response payload for Soulseek search results."""

    results: list[Any] = Field(
        ..., description="Raw search result entries returned by slskd (legacy shape)"
    )
    raw: dict[str, Any] | None = Field(
        None,
        description="Original payload emitted by slskd when available for debugging",
    )
    normalised: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Flattened file-level entries produced by SoulseekClient.normalise_search_results"
        ),
    )


class SoulseekDownloadResponse(BaseModel):
    """Response payload when a Soulseek download is queued."""

    status: str
    detail: dict[str, Any] | None = None


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


def _default_retryable_states() -> list[str]:
    allowed_db_states = set(_CANONICAL_DOWNLOAD_STATE_MAP.keys()) - set(
        _REQUEUE_PROHIBITED_DB_STATES
    )
    canonical_states = {_canonical_download_state(state) for state in allowed_db_states}
    return sorted(canonical_states)


SOULSEEK_RETRYABLE_STATES: tuple[str, ...] = tuple(_default_retryable_states())


def _retryable_states_default() -> list[str]:
    return list(SOULSEEK_RETRYABLE_STATES)


class SoulseekDownloadEntry(BaseModel):
    id: int
    filename: str
    db_state: str = Field(alias="state", exclude=True)
    progress: float
    created_at: datetime
    updated_at: datetime
    priority: int = 0
    organized_path: str | None = None
    genre: str | None = None
    composer: str | None = None
    producer: str | None = None
    isrc: str | None = None
    copyright: str | None = None
    artwork_url: str | None = None
    artwork_path: str | None = None
    artwork_status: str | None = None
    has_artwork: bool | None = None
    spotify_track_id: str | None = None
    spotify_album_id: str | None = None
    lyrics_status: str | None = None
    lyrics_path: str | None = None
    has_lyrics: bool | None = None
    retry_count: int = 0
    next_retry_at: datetime | None = None
    last_error: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field(return_type=str, alias="state")
    def state(self) -> str:
        return _canonical_download_state(self.db_state)


class SoulseekDownloadStatus(BaseModel):
    downloads: list[SoulseekDownloadEntry]
    retryable_states: list[str] = Field(default_factory=_retryable_states_default)


class DownloadEntryResponse(BaseModel):
    """Download information returned to API consumers."""

    id: int
    filename: str
    progress: float
    created_at: datetime
    updated_at: datetime
    priority: int = 0
    username: str | None = None
    organized_path: str | None = None
    genre: str | None = None
    composer: str | None = None
    producer: str | None = None
    isrc: str | None = None
    copyright: str | None = None
    artwork_url: str | None = None
    artwork_path: str | None = None
    artwork_status: str | None = None
    has_artwork: bool | None = None
    spotify_track_id: str | None = None
    spotify_album_id: str | None = None
    lyrics_status: str | None = None
    lyrics_path: str | None = None
    has_lyrics: bool | None = None
    db_state: str = Field(alias="state", exclude=True)
    retry_count: int = 0
    next_retry_at: datetime | None = None
    last_error: str | None = None
    live_queue: dict[str, Any] | None = None

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
    downloads: list[DownloadEntryResponse]


class SoulseekCancelResponse(BaseModel):
    cancelled: bool


class DownloadMetadataResponse(BaseModel):
    id: int
    filename: str
    genre: str | None = None
    composer: str | None = None
    producer: str | None = None
    isrc: str | None = None
    copyright: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DownloadPriorityUpdate(BaseModel):
    priority: int


class MatchingRequest(BaseModel):
    spotify_track: dict[str, Any]
    candidates: list[dict[str, Any]]


class MatchingResponse(BaseModel):
    best_match: dict[str, Any] | None
    confidence: float


class SettingsPayload(BaseModel):
    key: str
    value: str | None


class SettingsResponse(BaseModel):
    settings: dict[str, str | None]
    updated_at: datetime


class SettingsHistoryEntry(BaseModel):
    key: str
    old_value: str | None
    new_value: str | None
    changed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SettingsHistoryResponse(BaseModel):
    history: list[SettingsHistoryEntry]


class ArtistPreferenceEntry(BaseModel):
    artist_id: str
    release_id: str
    selected: bool


class ArtistPreferencesPayload(BaseModel):
    preferences: list[ArtistPreferenceEntry] = Field(default_factory=list)


class ArtistPreferencesResponse(BaseModel):
    preferences: list[ArtistPreferenceEntry]
