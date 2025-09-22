"""Pydantic schemas for request and response bodies."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StatusResponse(BaseModel):
    status: str


class SpotifySearchResponse(BaseModel):
    items: List[Dict[str, Any]]


class PlaylistResponse(BaseModel):
    playlists: List[Dict[str, Any]]


class TrackDetailResponse(BaseModel):
    track: Dict[str, Any]


class SoulseekSearchRequest(BaseModel):
    query: str


class SoulseekDownloadRequest(BaseModel):
    username: str = Field(..., description="Soulseek username hosting the files")
    files: List[Dict[str, Any]] = Field(..., description="List of files to download")


class SoulseekDownloadStatus(BaseModel):
    downloads: List[Dict[str, Any]]


class SoulseekCancelResponse(BaseModel):
    cancelled: bool


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
