"""Pydantic schemas for request and response bodies."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


class StatusResponse(BaseModel):
    status: str
    artist_count: Optional[int] = None
    album_count: Optional[int] = None
    track_count: Optional[int] = None
    last_scan: Optional[datetime] = None


class SpotifySearchResponse(BaseModel):
    items: List[Dict[str, Any]]


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

    model_config = ConfigDict(from_attributes=True)


class SoulseekDownloadStatus(BaseModel):
    downloads: List[SoulseekDownloadEntry]


class SoulseekCancelResponse(BaseModel):
    cancelled: bool


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
