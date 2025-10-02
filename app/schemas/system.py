"""System-level schema definitions (health, status, ping)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ISODateTime


class StatusResponse(BaseModel):
    status: str
    artist_count: Optional[int] = None
    album_count: Optional[int] = None
    track_count: Optional[int] = None
    last_scan: Optional[datetime] = None
    connections: Optional[Dict[str, str]] = None


class ServiceHealthResponse(BaseModel):
    service: str
    status: str
    missing: List[str] = Field(default_factory=list)
    optional_missing: List[str] = Field(default_factory=list)


class HealthStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    version: Optional[str] = None
    uptime_s: Optional[float] = Field(default=None, ge=0)


class VersionInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    build: Optional[str] = None
    commit: Optional[str] = None
    generated_at: ISODateTime


class Ping(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool = True
    at: ISODateTime
    meta: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "HealthStatus",
    "Ping",
    "ServiceHealthResponse",
    "StatusResponse",
    "VersionInfo",
]
