"""System-level schema definitions (health, status, ping)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ISODateTime


class StatusResponse(BaseModel):
    status: str
    artist_count: int | None = None
    album_count: int | None = None
    track_count: int | None = None
    last_scan: datetime | None = None
    connections: dict[str, str] | None = None


class ServiceHealthResponse(BaseModel):
    service: str
    status: str
    missing: list[str] = Field(default_factory=list)
    optional_missing: list[str] = Field(default_factory=list)


class HealthStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    version: str | None = None
    uptime_s: float | None = Field(default=None, ge=0)


class VersionInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    build: str | None = None
    commit: str | None = None
    generated_at: ISODateTime


class Ping(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool = True
    at: ISODateTime
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "HealthStatus",
    "Ping",
    "ServiceHealthResponse",
    "StatusResponse",
    "VersionInfo",
]
