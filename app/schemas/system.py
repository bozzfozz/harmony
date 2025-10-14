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


class FeatureFlagsInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    enable_artwork: bool
    enable_lyrics: bool
    enable_legacy_routes: bool
    enable_artist_cache_invalidation: bool
    enable_admin_api: bool


class WorkerEnvironmentState(BaseModel):
    model_config = ConfigDict(frozen=True)

    disable_workers: bool
    enabled_override: bool | None = None
    enabled_raw: str | None = None
    visibility_timeout_s: int | None = None
    watchlist_interval_s: float | None = None
    watchlist_timer_enabled: bool | None = None


class EnvironmentProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: str
    is_dev: bool
    is_test: bool
    is_staging: bool
    is_prod: bool
    workers: WorkerEnvironmentState


class OrchestratorSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    workers_enabled: bool
    global_concurrency: int
    visibility_timeout_s: int
    poll_interval_ms: int
    poll_interval_max_ms: int
    priority_map: dict[str, int]


class WatchlistTimerSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    interval_s: float


class BuildInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    started_at: ISODateTime


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_base_path: str
    feature_flags: FeatureFlagsInfo
    environment: EnvironmentProfile
    orchestrator: OrchestratorSettings
    watchlist_timer: WatchlistTimerSettings
    build: BuildInfo


__all__ = [
    "HealthStatus",
    "Ping",
    "ServiceHealthResponse",
    "StatusResponse",
    "VersionInfo",
    "EnvironmentResponse",
    "FeatureFlagsInfo",
    "EnvironmentProfile",
    "WorkerEnvironmentState",
    "OrchestratorSettings",
    "WatchlistTimerSettings",
    "BuildInfo",
]
