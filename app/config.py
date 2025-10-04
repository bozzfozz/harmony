"""Application configuration utilities for Harmony."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.logging import get_logger
from app.logging_events import log_event
from app.utils.priority import parse_priority_map


logger = get_logger(__name__)


@dataclass(slots=True)
class SpotifyConfig:
    client_id: Optional[str]
    client_secret: Optional[str]
    redirect_uri: Optional[str]
    scope: str
    free_import_max_lines: int
    free_import_max_file_bytes: int
    free_import_max_playlist_links: int
    free_import_hard_cap_multiplier: int
    free_accept_user_urls: bool
    backfill_max_items: int
    backfill_cache_ttl_seconds: int


@dataclass(slots=True)
class SoulseekConfig:
    base_url: str
    api_key: Optional[str]
    timeout_ms: int
    retry_max: int
    retry_backoff_base_ms: int
    retry_jitter_pct: float
    preferred_formats: tuple[str, ...]
    max_results: int


@dataclass(slots=True)
class LoggingConfig:
    level: str


@dataclass(slots=True)
class DatabaseConfig:
    url: str


@dataclass(slots=True)
class ArtworkFallbackConfig:
    enabled: bool
    provider: str
    timeout_seconds: float
    max_bytes: int


@dataclass(slots=True)
class ArtworkPostProcessingConfig:
    enabled: bool = False
    hooks: tuple[str, ...] = ()


@dataclass(slots=True)
class ArtworkConfig:
    directory: str
    timeout_seconds: float
    max_bytes: int
    concurrency: int
    min_edge: int
    min_bytes: int
    fallback: ArtworkFallbackConfig
    post_processing: ArtworkPostProcessingConfig = field(
        default_factory=ArtworkPostProcessingConfig
    )


@dataclass(slots=True)
class FreeIngestConfig:
    max_playlists: int
    max_tracks: int
    batch_size: int


@dataclass(slots=True)
class IngestConfig:
    batch_size: int
    max_pending_jobs: int


@dataclass(slots=True)
class FeatureFlags:
    enable_artwork: bool
    enable_lyrics: bool
    enable_legacy_routes: bool


@dataclass(slots=True)
class IntegrationsConfig:
    enabled: tuple[str, ...]
    timeouts_ms: dict[str, int]
    max_concurrency: int


@dataclass(slots=True)
class HealthConfig:
    db_timeout_ms: int
    dependency_timeout_ms: int
    dependencies: tuple[str, ...]
    require_database: bool


@dataclass(slots=True)
class WatchlistWorkerConfig:
    max_concurrency: int
    max_per_tick: int
    spotify_timeout_ms: int
    slskd_search_timeout_ms: int
    tick_budget_ms: int
    backoff_base_ms: int
    retry_max: int
    jitter_pct: float
    shutdown_grace_ms: int
    db_io_mode: str
    retry_budget_per_artist: int
    cooldown_minutes: int


@dataclass(slots=True, frozen=True)
class ExternalCallPolicy:
    timeout_ms: int
    retry_max: int
    backoff_base_ms: int
    jitter_pct: float

    @classmethod
    def from_env(cls, env: Mapping[str, Any]) -> "ExternalCallPolicy":
        timeout_ms = _bounded_int(
            env.get("EXTERNAL_TIMEOUT_MS"),
            default=DEFAULT_EXTERNAL_TIMEOUT_MS,
            minimum=100,
        )
        retry_max = _bounded_int(
            env.get("EXTERNAL_RETRY_MAX"),
            default=DEFAULT_EXTERNAL_RETRY_MAX,
            minimum=0,
        )
        backoff_base = _bounded_int(
            env.get("EXTERNAL_BACKOFF_BASE_MS"),
            default=DEFAULT_EXTERNAL_BACKOFF_BASE_MS,
            minimum=1,
        )
        jitter_pct = _parse_jitter_value(
            env.get("EXTERNAL_JITTER_PCT"),
            default_pct=DEFAULT_EXTERNAL_JITTER_PCT,
        )
        return cls(
            timeout_ms=timeout_ms,
            retry_max=retry_max,
            backoff_base_ms=backoff_base,
            jitter_pct=jitter_pct,
        )


@dataclass(slots=True, frozen=True)
class ProviderProfile:
    name: str
    policy: ExternalCallPolicy


@dataclass(slots=True, frozen=True)
class WatchlistTimerConfig:
    enabled: bool
    interval_s: float

    @classmethod
    def from_env(cls, env: Mapping[str, Any]) -> "WatchlistTimerConfig":
        enabled = _as_bool(
            str(env.get("WATCHLIST_TIMER_ENABLED")) if "WATCHLIST_TIMER_ENABLED" in env else None,
            default=DEFAULT_WATCHLIST_TIMER_ENABLED,
        )
        interval = _bounded_float(
            env.get("WATCHLIST_TIMER_INTERVAL_S"),
            default=DEFAULT_WATCHLIST_TIMER_INTERVAL_S,
            minimum=0.0,
        )
        return cls(enabled=enabled, interval_s=interval)


@dataclass(slots=True, frozen=True)
class OrchestratorConfig:
    workers_enabled: bool
    global_concurrency: int
    pool_sync: int
    pool_matching: int
    pool_retry: int
    pool_watchlist: int
    priority_map: dict[str, int]
    visibility_timeout_s: int
    heartbeat_s: int
    poll_interval_ms: int
    poll_interval_max_ms: int

    def pool_limits(self) -> dict[str, int]:
        return {
            "sync": max(1, self.pool_sync or self.global_concurrency),
            "matching": max(1, self.pool_matching or self.global_concurrency),
            "retry": max(1, self.pool_retry or self.global_concurrency),
            "watchlist": max(1, self.pool_watchlist or self.global_concurrency),
        }

    @classmethod
    def from_env(cls, env: Mapping[str, Any]) -> "OrchestratorConfig":
        workers_enabled = _as_bool(
            str(env.get("WORKERS_ENABLED")) if "WORKERS_ENABLED" in env else None,
            default=DEFAULT_ORCHESTRATOR_WORKERS_ENABLED,
        )
        global_limit = _bounded_int(
            env.get("ORCH_GLOBAL_CONCURRENCY"),
            default=DEFAULT_ORCH_GLOBAL_CONCURRENCY,
            minimum=1,
        )
        pool_sync = _bounded_int(
            env.get("ORCH_POOL_SYNC"),
            default=DEFAULT_ORCH_POOL_SYNC,
            minimum=1,
        )
        pool_matching = _bounded_int(
            env.get("ORCH_POOL_MATCHING"),
            default=DEFAULT_ORCH_POOL_MATCHING,
            minimum=1,
        )
        pool_retry = _bounded_int(
            env.get("ORCH_POOL_RETRY"),
            default=DEFAULT_ORCH_POOL_RETRY,
            minimum=1,
        )
        pool_watchlist = _bounded_int(
            env.get("ORCH_POOL_WATCHLIST"),
            default=DEFAULT_ORCH_POOL_WATCHLIST,
            minimum=1,
        )
        visibility_timeout = _bounded_int(
            env.get("ORCH_VISIBILITY_TIMEOUT_S"),
            default=DEFAULT_ORCH_VISIBILITY_TIMEOUT_S,
            minimum=5,
        )
        heartbeat_s = _bounded_int(
            env.get("ORCH_HEARTBEAT_S"),
            default=DEFAULT_ORCH_HEARTBEAT_S,
            minimum=1,
        )
        poll_interval = _bounded_int(
            env.get("ORCH_POLL_INTERVAL_MS"),
            default=DEFAULT_ORCH_POLL_INTERVAL_MS,
            minimum=10,
        )
        poll_interval_max = _bounded_int(
            env.get("ORCH_POLL_INTERVAL_MAX_MS"),
            default=DEFAULT_ORCH_POLL_INTERVAL_MAX_MS,
            minimum=poll_interval,
        )
        priority_map = _parse_priority_map(env)
        return cls(
            workers_enabled=workers_enabled,
            global_concurrency=global_limit,
            pool_sync=pool_sync,
            pool_matching=pool_matching,
            pool_retry=pool_retry,
            pool_watchlist=pool_watchlist,
            priority_map=priority_map,
            visibility_timeout_s=visibility_timeout,
            heartbeat_s=heartbeat_s,
            poll_interval_ms=poll_interval,
            poll_interval_max_ms=poll_interval_max,
        )


@dataclass(slots=True, frozen=True)
class RetryPolicyConfig:
    max_attempts: int
    base_seconds: float
    jitter_pct: float


@dataclass(slots=True)
class MatchingConfig:
    edition_aware: bool
    fuzzy_max_candidates: int
    min_artist_similarity: float
    complete_threshold: float
    nearly_threshold: float


@dataclass(slots=True, frozen=True)
class WorkerEnvironmentConfig:
    disable_workers: bool
    enabled_override: bool | None
    enabled_raw: str | None
    visibility_timeout_s: int | None
    watchlist_interval_s: float | None
    watchlist_timer_enabled: bool | None


@dataclass(slots=True, frozen=True)
class EnvironmentConfig:
    profile: str
    is_dev: bool
    is_test: bool
    is_staging: bool
    is_prod: bool
    workers: WorkerEnvironmentConfig


@dataclass(slots=True)
class AppConfig:
    spotify: SpotifyConfig
    soulseek: SoulseekConfig
    logging: LoggingConfig
    database: DatabaseConfig
    artwork: ArtworkConfig
    ingest: IngestConfig
    free_ingest: FreeIngestConfig
    features: FeatureFlags
    integrations: IntegrationsConfig
    security: "SecurityConfig"
    middleware: MiddlewareConfig
    api_base_path: str
    health: HealthConfig
    watchlist: WatchlistWorkerConfig
    matching: MatchingConfig
    environment: EnvironmentConfig


@dataclass(slots=True, frozen=True)
class SecurityProfileDefaults:
    name: str
    require_auth: bool
    rate_limiting: bool


DEFAULT_SECURITY_PROFILE = "default"
_SECURITY_PROFILE_DEFAULTS: Mapping[str, SecurityProfileDefaults] = {
    "default": SecurityProfileDefaults(
        name="default",
        require_auth=False,
        rate_limiting=False,
    ),
    "dev": SecurityProfileDefaults(
        name="dev",
        require_auth=False,
        rate_limiting=False,
    ),
    "test": SecurityProfileDefaults(
        name="test",
        require_auth=False,
        rate_limiting=False,
    ),
    "staging": SecurityProfileDefaults(
        name="staging",
        require_auth=False,
        rate_limiting=False,
    ),
    "prod": SecurityProfileDefaults(
        name="prod",
        require_auth=True,
        rate_limiting=True,
    ),
}

_SECURITY_PROFILE_ALIASES: Mapping[str, str] = {
    "production": "prod",
    "live": "prod",
    "development": "dev",
    "local": "dev",
    "testing": "test",
}


@dataclass(slots=True)
class SecurityConfig:
    profile: str
    api_keys: tuple[str, ...]
    allowlist: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    _require_auth_default: bool
    _rate_limiting_default: bool
    _require_auth_override: bool | None = None
    _rate_limiting_override: bool | None = None

    @property
    def require_auth_default(self) -> bool:
        return self._require_auth_default

    @property
    def rate_limiting_default(self) -> bool:
        return self._rate_limiting_default

    def resolve_require_auth(self) -> bool:
        if self._require_auth_override is not None:
            return self._require_auth_override
        return self._require_auth_default

    def resolve_rate_limiting_enabled(self) -> bool:
        if self._rate_limiting_override is not None:
            return self._rate_limiting_override
        return self._rate_limiting_default

    @property
    def require_auth(self) -> bool:
        return self.resolve_require_auth()

    @require_auth.setter
    def require_auth(self, value: bool | None) -> None:
        self._require_auth_override = bool(value) if value is not None else None

    @property
    def rate_limiting_enabled(self) -> bool:
        return self.resolve_rate_limiting_enabled()

    @rate_limiting_enabled.setter
    def rate_limiting_enabled(self, value: bool | None) -> None:
        self._rate_limiting_override = bool(value) if value is not None else None

    def clear_profile_overrides(self) -> None:
        self._require_auth_override = None
        self._rate_limiting_override = None


def _resolve_security_profile(env: Mapping[str, Any]) -> tuple[str, SecurityProfileDefaults]:
    raw = str(env.get("HARMONY_PROFILE") or "").strip().lower()
    if not raw:
        key = DEFAULT_SECURITY_PROFILE
    else:
        candidate = _SECURITY_PROFILE_ALIASES.get(raw, raw)
        if candidate not in _SECURITY_PROFILE_DEFAULTS:
            logger.warning(
                "Unknown HARMONY_PROFILE value %s; defaulting to %s",
                raw,
                DEFAULT_SECURITY_PROFILE,
            )
            key = DEFAULT_SECURITY_PROFILE
        else:
            key = candidate
    defaults = _SECURITY_PROFILE_DEFAULTS[key]
    return defaults.name, defaults


@dataclass(slots=True)
class RequestMiddlewareConfig:
    header_name: str


@dataclass(slots=True)
class RateLimitMiddlewareConfig:
    enabled: bool
    bucket_capacity: int
    refill_per_second: float


@dataclass(slots=True, frozen=True)
class CacheRule:
    pattern: str
    ttl: int | None
    stale_while_revalidate: int | None


@dataclass(slots=True)
class CacheMiddlewareConfig:
    enabled: bool
    default_ttl: int
    max_items: int
    etag_strategy: str
    fail_open: bool
    stale_while_revalidate: int | None
    cacheable_paths: tuple[CacheRule, ...]


@dataclass(slots=True)
class CorsMiddlewareConfig:
    allowed_origins: tuple[str, ...]
    allowed_headers: tuple[str, ...]
    allowed_methods: tuple[str, ...]


@dataclass(slots=True)
class GZipMiddlewareConfig:
    min_size: int


@dataclass(slots=True)
class MiddlewareConfig:
    request_id: RequestMiddlewareConfig
    rate_limit: RateLimitMiddlewareConfig
    cache: CacheMiddlewareConfig
    cors: CorsMiddlewareConfig
    gzip: GZipMiddlewareConfig


@dataclass(slots=True, frozen=True)
class Settings:
    orchestrator: OrchestratorConfig
    external: ExternalCallPolicy
    watchlist_timer: WatchlistTimerConfig
    provider_profiles: dict[str, ProviderProfile]
    retry_policy: "RetryPolicyConfig"

    @classmethod
    def load(cls, env: Mapping[str, Any] | None = None) -> "Settings":
        if env is None:
            env_map: dict[str, Any] = dict(os.environ)
        else:
            env_map = dict(env)
        orchestrator = OrchestratorConfig.from_env(env_map)
        external = ExternalCallPolicy.from_env(env_map)
        watchlist_timer = WatchlistTimerConfig.from_env(env_map)
        profiles = _load_provider_profiles(env_map, external)
        return cls(
            orchestrator=orchestrator,
            external=external,
            watchlist_timer=watchlist_timer,
            provider_profiles=profiles,
            retry_policy=_load_retry_policy(env_map),
        )


DEFAULT_DB_URL = "sqlite:///./harmony.db"
DEFAULT_SOULSEEK_URL = "http://localhost:5030"
DEFAULT_SOULSEEK_PORT = urlparse(DEFAULT_SOULSEEK_URL).port or 5030
DEFAULT_SPOTIFY_SCOPE = "user-library-read playlist-read-private playlist-read-collaborative"
DEFAULT_ARTWORK_DIR = "./artwork"
DEFAULT_ARTWORK_TIMEOUT = 15.0
DEFAULT_ARTWORK_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_ARTWORK_CONCURRENCY = 2
DEFAULT_ARTWORK_MIN_EDGE = 1000
DEFAULT_ARTWORK_MIN_BYTES = 150_000
DEFAULT_ARTWORK_FALLBACK_TIMEOUT = 12.0
DEFAULT_ARTWORK_FALLBACK_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_FREE_IMPORT_MAX_LINES = 200
DEFAULT_FREE_IMPORT_MAX_FILE_BYTES = 1_048_576
DEFAULT_FREE_IMPORT_MAX_PLAYLIST_LINKS = 1_000
DEFAULT_FREE_IMPORT_HARD_CAP_MULTIPLIER = 10
DEFAULT_FREE_INGEST_MAX_PLAYLISTS = 100
DEFAULT_FREE_INGEST_MAX_TRACKS = 5_000
DEFAULT_FREE_INGEST_BATCH_SIZE = 500
DEFAULT_INGEST_BATCH_SIZE = 500
DEFAULT_INGEST_MAX_PENDING_JOBS = 100
DEFAULT_BACKFILL_MAX_ITEMS = 2_000
DEFAULT_BACKFILL_CACHE_TTL = 604_800
DEFAULT_API_BASE_PATH = "/api/v1"
DEFAULT_ALLOWLIST_SUFFIXES = ("/health", "/ready", "/docs", "/redoc", "/openapi.json")
DEFAULT_CACHEABLE_PATH_PATTERNS = (
    "^/$|30|120",
    "^/activity$|60|180",
    "^/activity/export$|300|600",
    "^/spotify(?:/.*)?$|45|180",
)
DEFAULT_PROVIDER_MAX_CONCURRENCY = 4
DEFAULT_SLSKD_TIMEOUT_MS = 8_000
DEFAULT_SLSKD_RETRY_MAX = 3
DEFAULT_SLSKD_RETRY_BACKOFF_BASE_MS = 250
DEFAULT_SLSKD_RETRY_JITTER_PCT = 20.0
DEFAULT_SLSKD_PREFERRED_FORMATS = ("FLAC", "ALAC", "APE", "MP3")
DEFAULT_SLSKD_MAX_RESULTS = 50
DEFAULT_HEALTH_DB_TIMEOUT_MS = 500
DEFAULT_HEALTH_DEP_TIMEOUT_MS = 800
DEFAULT_WATCHLIST_MAX_CONCURRENCY = 3
DEFAULT_WATCHLIST_MAX_PER_TICK = 20
DEFAULT_WATCHLIST_SPOTIFY_TIMEOUT_MS = 8_000
DEFAULT_WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS = 12_000
DEFAULT_WATCHLIST_TICK_BUDGET_MS = 8_000
DEFAULT_WATCHLIST_BACKOFF_BASE_MS = 250
DEFAULT_WATCHLIST_RETRY_MAX = 3

DEFAULT_ORCHESTRATOR_WORKERS_ENABLED = True
DEFAULT_ORCH_GLOBAL_CONCURRENCY = 8
DEFAULT_ORCH_POOL_SYNC = 4
DEFAULT_ORCH_POOL_MATCHING = 4
DEFAULT_ORCH_POOL_RETRY = 2
DEFAULT_ORCH_POOL_WATCHLIST = 2
DEFAULT_ORCH_PRIORITY_MAP = {
    "sync": 100,
    "matching": 90,
    "retry": 80,
    "watchlist": 50,
}
DEFAULT_ORCH_VISIBILITY_TIMEOUT_S = 60
DEFAULT_ORCH_HEARTBEAT_S = 20
DEFAULT_ORCH_POLL_INTERVAL_MS = 200
DEFAULT_ORCH_POLL_INTERVAL_MAX_MS = 2000

DEFAULT_EXTERNAL_TIMEOUT_MS = 10_000
DEFAULT_EXTERNAL_RETRY_MAX = 3
DEFAULT_EXTERNAL_BACKOFF_BASE_MS = 250
DEFAULT_EXTERNAL_JITTER_PCT = 20.0

DEFAULT_WATCHLIST_TIMER_ENABLED = True
DEFAULT_WATCHLIST_TIMER_INTERVAL_S = 900.0
DEFAULT_WATCHLIST_JITTER_PCT = 0.2
DEFAULT_WATCHLIST_SHUTDOWN_GRACE_MS = 2_000
DEFAULT_WATCHLIST_DB_IO_MODE = "thread"
DEFAULT_WATCHLIST_RETRY_BUDGET_PER_ARTIST = 6
DEFAULT_WATCHLIST_COOLDOWN_MINUTES = 15
DEFAULT_MATCH_FUZZY_MAX_CANDIDATES = 50
DEFAULT_MATCH_MIN_ARTIST_SIM = 0.6
DEFAULT_MATCH_COMPLETE_THRESHOLD = 0.9
DEFAULT_MATCH_NEARLY_THRESHOLD = 0.8
DEFAULT_RETRY_MAX_ATTEMPTS = 10
DEFAULT_RETRY_BASE_SECONDS = 60.0
DEFAULT_RETRY_JITTER_PCT = 0.2


def _as_bool(value: Optional[str], *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Optional[str], *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    resolved = _coerce_int(value, default=default)
    if minimum is not None:
        resolved = max(minimum, resolved)
    if maximum is not None:
        resolved = min(maximum, resolved)
    return resolved


def _parse_list(value: Optional[str]) -> list[str]:
    if value is None:
        return []
    candidates = value.replace("\n", ",").split(",")
    return [item.strip() for item in candidates if item.strip()]


def _bounded_float(
    value: Any,
    *,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        resolved = default
    if minimum is not None:
        resolved = max(minimum, resolved)
    if maximum is not None:
        resolved = min(maximum, resolved)
    return resolved


def _parse_bool_override(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    logger.warning("Ignoring invalid boolean override value: %s", value)
    return None


def _parse_optional_int(
    value: Any,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    if value is None:
        return None
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid integer override value: %s", value)
        return None
    if minimum is not None and resolved < minimum:
        logger.warning(
            "Integer override %s below minimum %s; clamping", value, minimum
        )
        resolved = minimum
    if maximum is not None and resolved > maximum:
        resolved = maximum
    return resolved


def _parse_optional_float(
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value is None:
        return None
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid float override value: %s", value)
        return None
    if minimum is not None and resolved < minimum:
        logger.warning(
            "Float override %s below minimum %s; clamping", value, minimum
        )
        resolved = minimum
    if maximum is not None and resolved > maximum:
        resolved = maximum
    return resolved


def _parse_enabled_providers(value: Optional[str]) -> tuple[str, ...]:
    if not value:
        return ("spotify", "slskd")
    items = [entry.strip().lower() for entry in value.replace("\n", ",").split(",")]
    deduplicated: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            deduplicated.append(item)
    return tuple(deduplicated or ("spotify", "slskd"))


def _parse_dependency_names(value: Optional[str]) -> tuple[str, ...]:
    if not value:
        return ()
    items = [entry.strip().lower() for entry in value.replace("\n", ",").split(",")]
    deduplicated: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            deduplicated.append(item)
    return tuple(deduplicated)


def _parse_provider_timeouts(env: Mapping[str, Optional[str]]) -> dict[str, int]:
    defaults: dict[str, int] = {
        "spotify": 15000,
        "plex": 15000,
        "slskd": DEFAULT_SLSKD_TIMEOUT_MS,
    }
    for key, provider in (
        ("SPOTIFY_TIMEOUT_MS", "spotify"),
        ("PLEX_TIMEOUT_MS", "plex"),
        ("SLSKD_TIMEOUT_MS", "slskd"),
    ):
        raw = env.get(key)
        if raw is None:
            continue
        try:
            defaults[provider] = max(200, int(raw))
        except (TypeError, ValueError):
            continue
    return defaults


def _parse_jitter_value(value: Any, *, default_pct: float) -> float:
    resolved = default_pct
    if value is not None:
        try:
            resolved = float(value)
        except (TypeError, ValueError):
            resolved = default_pct
    if resolved < 0:
        return 0.0
    if resolved <= 1:
        return resolved
    return resolved / 100.0


def _parse_priority_map(env: Mapping[str, Any]) -> dict[str, int]:
    default_map = dict(DEFAULT_ORCH_PRIORITY_MAP)
    raw_json = env.get("ORCH_PRIORITY_JSON")
    if raw_json:
        mapping = parse_priority_map(str(raw_json), {})
        filtered = {key: value for key, value in mapping.items() if key in default_map}
        if filtered:
            return filtered
    raw_csv = env.get("ORCH_PRIORITY_CSV")
    if raw_csv:
        mapping = parse_priority_map(str(raw_csv), {})
        filtered = {key: value for key, value in mapping.items() if key in default_map}
        if filtered:
            return filtered
    return default_map


def _load_provider_profiles(
    env: Mapping[str, Any], default_policy: ExternalCallPolicy
) -> dict[str, ProviderProfile]:
    profiles: dict[str, ProviderProfile] = {}
    candidates = {"spotify", "slskd", "plex"}
    for provider in candidates:
        prefix = f"PROVIDER_{provider.upper()}"
        keys = {
            "timeout": f"{prefix}_TIMEOUT_MS",
            "retry": f"{prefix}_RETRY_MAX",
            "backoff": f"{prefix}_BACKOFF_BASE_MS",
            "jitter": f"{prefix}_JITTER_PCT",
        }
        if not any(key in env for key in keys.values()):
            continue
        policy = ExternalCallPolicy(
            timeout_ms=_bounded_int(
                env.get(keys["timeout"]),
                default=default_policy.timeout_ms,
                minimum=100,
            ),
            retry_max=_bounded_int(
                env.get(keys["retry"]),
                default=default_policy.retry_max,
                minimum=0,
            ),
            backoff_base_ms=_bounded_int(
                env.get(keys["backoff"]),
                default=default_policy.backoff_base_ms,
                minimum=1,
            ),
            jitter_pct=_parse_jitter_value(
                env.get(keys["jitter"]),
                default_pct=default_policy.jitter_pct,
            ),
        )
        profiles[provider] = ProviderProfile(name=provider, policy=policy)
    return profiles


def _resolve_environment_profile(env: Mapping[str, Any]) -> tuple[str, dict[str, bool]]:
    raw = str(env.get("APP_ENV") or env.get("ENVIRONMENT") or "").strip()
    if not raw and env.get("PYTEST_CURRENT_TEST"):
        raw = "test"
    normalized = raw.lower()
    aliases = {
        "development": "dev",
        "local": "dev",
        "production": "prod",
        "live": "prod",
        "stage": "staging",
    }
    normalized = aliases.get(normalized, normalized)
    valid = {"dev", "staging", "prod", "test"}
    if normalized not in valid:
        if normalized:
            logger.warning("Unknown APP_ENV value %s; defaulting to dev", raw)
        normalized = "dev"
    flags = {
        "is_dev": normalized == "dev",
        "is_test": normalized == "test",
        "is_staging": normalized == "staging",
        "is_prod": normalized == "prod",
    }
    return normalized, flags


def _load_environment_config(env: Mapping[str, Any]) -> EnvironmentConfig:
    profile, flags = _resolve_environment_profile(env)
    workers_enabled_raw = env.get("WORKERS_ENABLED")
    workers_enabled_override = _parse_bool_override(workers_enabled_raw)
    disable_workers = _as_bool(
        str(env.get("HARMONY_DISABLE_WORKERS"))
        if "HARMONY_DISABLE_WORKERS" in env
        else None,
        default=False,
    )
    visibility_override = _parse_optional_int(
        env.get("WORKER_VISIBILITY_TIMEOUT_S"), minimum=5
    )
    watchlist_interval = _parse_optional_float(env.get("WATCHLIST_INTERVAL"))
    watchlist_timer_enabled = _parse_bool_override(env.get("WATCHLIST_TIMER_ENABLED"))

    workers = WorkerEnvironmentConfig(
        disable_workers=disable_workers,
        enabled_override=workers_enabled_override,
        enabled_raw=str(workers_enabled_raw) if workers_enabled_raw is not None else None,
        visibility_timeout_s=visibility_override,
        watchlist_interval_s=watchlist_interval,
        watchlist_timer_enabled=watchlist_timer_enabled,
    )

    return EnvironmentConfig(
        profile=profile,
        is_dev=flags["is_dev"],
        is_test=flags["is_test"],
        is_staging=flags["is_staging"],
        is_prod=flags["is_prod"],
        workers=workers,
    )


def _load_retry_policy(env: Mapping[str, Any]) -> RetryPolicyConfig:
    max_attempts = _bounded_int(
        env.get("RETRY_MAX_ATTEMPTS"),
        default=DEFAULT_RETRY_MAX_ATTEMPTS,
        minimum=1,
    )
    base_seconds = _bounded_float(
        env.get("RETRY_BASE_SECONDS"),
        default=DEFAULT_RETRY_BASE_SECONDS,
        minimum=1e-3,
    )
    jitter_pct = _parse_jitter_value(
        env.get("RETRY_JITTER_PCT"),
        default_pct=DEFAULT_RETRY_JITTER_PCT,
    )
    return RetryPolicyConfig(
        max_attempts=max_attempts,
        base_seconds=base_seconds,
        jitter_pct=jitter_pct,
    )


settings = Settings.load()

log_event(
    logger,
    "config.loaded",
    component="config",
    status="ok",
    meta={
        "orchestrator": {
            "workers_enabled": settings.orchestrator.workers_enabled,
            "global_concurrency": settings.orchestrator.global_concurrency,
            "poll_interval_ms": settings.orchestrator.poll_interval_ms,
            "poll_interval_max_ms": settings.orchestrator.poll_interval_max_ms,
            "visibility_timeout_s": settings.orchestrator.visibility_timeout_s,
        },
        "external": {
            "timeout_ms": settings.external.timeout_ms,
            "retry_max": settings.external.retry_max,
            "backoff_base_ms": settings.external.backoff_base_ms,
            "jitter_pct": settings.external.jitter_pct,
        },
        "watchlist_timer": {
            "enabled": settings.watchlist_timer.enabled,
            "interval_s": settings.watchlist_timer.interval_s,
        },
        "provider_profiles": sorted(settings.provider_profiles.keys()),
        "retry_policy": {
            "max_attempts": settings.retry_policy.max_attempts,
            "base_seconds": settings.retry_policy.base_seconds,
            "jitter_pct": settings.retry_policy.jitter_pct,
        },
    },
)


def _read_api_keys_from_file(path: str) -> list[str]:
    if not path:
        return []
    try:
        contents = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    return [line.strip() for line in contents.splitlines() if line.strip()]


def _deduplicate_preserve_order(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _parse_optional_duration(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _parse_cache_rules(values: Iterable[str]) -> tuple[CacheRule, ...]:
    rules: list[CacheRule] = []
    for raw_value in values:
        if not raw_value:
            continue
        segments = raw_value.split("|")
        pattern = segments[0].strip()
        if not pattern:
            continue
        ttl = None
        stale = None
        if len(segments) > 1:
            ttl = _parse_optional_duration(segments[1].strip() or None)
        if len(segments) > 2:
            stale = _parse_optional_duration(segments[2].strip() or None)
        rules.append(CacheRule(pattern=pattern, ttl=ttl, stale_while_revalidate=stale))
    return tuple(rules)


def _normalise_prefix(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    if cleaned != "/":
        cleaned = cleaned.rstrip("/")
    return cleaned


def _normalise_base_path(value: Optional[str]) -> str:
    candidate = value if value is not None else DEFAULT_API_BASE_PATH
    normalized = _normalise_prefix(candidate)
    if normalized == "":
        return ""
    return normalized


def _compose_allowlist_entry(base_path: str, suffix: str) -> str:
    normalized_suffix = _normalise_prefix(suffix)
    if not normalized_suffix or normalized_suffix == "/":
        return base_path or "/"
    if not base_path or base_path == "/":
        return normalized_suffix
    return f"{base_path}{normalized_suffix}"


def _as_float(value: Optional[str], *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_matching_config() -> MatchingConfig:
    """Return configuration values that control the matching engine."""

    edition_aware = _as_bool(
        os.getenv("FEATURE_MATCHING_EDITION_AWARE"),
        default=True,
    )
    fuzzy_max = max(
        5,
        _as_int(
            os.getenv("MATCH_FUZZY_MAX_CANDIDATES"),
            default=DEFAULT_MATCH_FUZZY_MAX_CANDIDATES,
        ),
    )
    min_artist = max(
        0.0,
        min(
            1.0,
            _as_float(
                os.getenv("MATCH_MIN_ARTIST_SIM"),
                default=DEFAULT_MATCH_MIN_ARTIST_SIM,
            ),
        ),
    )
    complete = max(
        0.0,
        min(
            1.0,
            _as_float(
                os.getenv("MATCH_COMPLETE_THRESHOLD"),
                default=DEFAULT_MATCH_COMPLETE_THRESHOLD,
            ),
        ),
    )
    nearly = max(
        0.0,
        min(
            complete,
            _as_float(
                os.getenv("MATCH_NEARLY_THRESHOLD"),
                default=DEFAULT_MATCH_NEARLY_THRESHOLD,
            ),
        ),
    )
    return MatchingConfig(
        edition_aware=edition_aware,
        fuzzy_max_candidates=fuzzy_max,
        min_artist_similarity=min_artist,
        complete_threshold=complete,
        nearly_threshold=nearly,
    )


def _load_settings_from_db(
    keys: Iterable[str], *, database_url: Optional[str] = None
) -> dict[str, Optional[str]]:
    """Fetch selected settings from the database."""

    database_url = database_url or os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    if not database_url:
        return {}

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}

    try:
        engine = create_engine(database_url, connect_args=connect_args)
    except SQLAlchemyError:
        return {}

    settings: dict[str, Optional[str]] = {}
    try:
        with engine.connect() as connection:
            for key in keys:
                try:
                    row = connection.execute(
                        text("SELECT value FROM settings WHERE key = :key LIMIT 1"),
                        {"key": key},
                    ).first()
                except SQLAlchemyError:
                    return {}

                if row is not None:
                    # Preserve keys found in the database, even if the value is NULL.
                    settings[key] = row[0]
    except SQLAlchemyError:
        return {}
    finally:
        engine.dispose()

    return settings


def get_setting(key: str, *, database_url: Optional[str] = None) -> Optional[str]:
    """Return a single setting value from the database if available."""

    settings = _load_settings_from_db([key], database_url=database_url)
    return settings.get(key)


def _resolve_setting(
    key: str,
    *,
    db_settings: Mapping[str, Optional[str]],
    fallback: Optional[str],
) -> Optional[str]:
    if key in db_settings:
        value = db_settings[key]
        return fallback if value is None else value
    return fallback


def _legacy_slskd_url() -> Optional[str]:
    host = (os.getenv("SLSKD_HOST") or "").strip()
    port = (os.getenv("SLSKD_PORT") or "").strip()

    if not host:
        return None

    if not port:
        port = str(DEFAULT_SOULSEEK_PORT)

    return f"http://{host}:{port}"


def load_config() -> AppConfig:
    """Load application configuration prioritising database backed settings."""

    database_url = os.getenv("DATABASE_URL", DEFAULT_DB_URL)

    config_keys = [
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "SPOTIFY_REDIRECT_URI",
        "SLSKD_URL",
        "SLSKD_API_KEY",
        "ENABLE_ARTWORK",
        "ENABLE_LYRICS",
    ]
    db_settings = dict(_load_settings_from_db(config_keys, database_url=database_url))
    legacy_slskd_url = _legacy_slskd_url()
    if legacy_slskd_url is not None:
        db_settings.pop("SLSKD_URL", None)

    environment_config = _load_environment_config(os.environ)

    spotify = SpotifyConfig(
        client_id=_resolve_setting(
            "SPOTIFY_CLIENT_ID",
            db_settings=db_settings,
            fallback=os.getenv("SPOTIFY_CLIENT_ID"),
        ),
        client_secret=_resolve_setting(
            "SPOTIFY_CLIENT_SECRET",
            db_settings=db_settings,
            fallback=os.getenv("SPOTIFY_CLIENT_SECRET"),
        ),
        redirect_uri=_resolve_setting(
            "SPOTIFY_REDIRECT_URI",
            db_settings=db_settings,
            fallback=os.getenv("SPOTIFY_REDIRECT_URI"),
        ),
        scope=os.getenv("SPOTIFY_SCOPE", DEFAULT_SPOTIFY_SCOPE),
        free_import_max_lines=max(
            1,
            _as_int(
                os.getenv("FREE_IMPORT_MAX_LINES"),
                default=DEFAULT_FREE_IMPORT_MAX_LINES,
            ),
        ),
        free_import_max_file_bytes=max(
            1,
            _as_int(
                os.getenv("FREE_IMPORT_MAX_FILE_BYTES"),
                default=DEFAULT_FREE_IMPORT_MAX_FILE_BYTES,
            ),
        ),
        free_import_max_playlist_links=max(
            1,
            _as_int(
                os.getenv("FREE_IMPORT_MAX_PLAYLIST_LINKS"),
                default=DEFAULT_FREE_IMPORT_MAX_PLAYLIST_LINKS,
            ),
        ),
        free_import_hard_cap_multiplier=max(
            1,
            _as_int(
                os.getenv("FREE_IMPORT_HARD_CAP_MULTIPLIER"),
                default=DEFAULT_FREE_IMPORT_HARD_CAP_MULTIPLIER,
            ),
        ),
        free_accept_user_urls=_as_bool(
            os.getenv("FREE_ACCEPT_USER_URLS"),
            default=False,
        ),
        backfill_max_items=max(
            1,
            _as_int(
                os.getenv("BACKFILL_MAX_ITEMS"),
                default=DEFAULT_BACKFILL_MAX_ITEMS,
            ),
        ),
        backfill_cache_ttl_seconds=max(
            60,
            _as_int(
                os.getenv("BACKFILL_CACHE_TTL_SEC"),
                default=DEFAULT_BACKFILL_CACHE_TTL,
            ),
        ),
    )

    soulseek_base_env = (
        os.getenv("SLSKD_BASE_URL")
        or os.getenv("SLSKD_URL")
        or legacy_slskd_url
        or DEFAULT_SOULSEEK_URL
    )
    timeout_ms = max(
        200,
        _as_int(
            os.getenv("SLSKD_TIMEOUT_MS"),
            default=DEFAULT_SLSKD_TIMEOUT_MS,
        ),
    )
    retry_max = max(
        0,
        _as_int(
            os.getenv("SLSKD_RETRY_MAX"),
            default=DEFAULT_SLSKD_RETRY_MAX,
        ),
    )
    retry_backoff_base_ms = max(
        50,
        _as_int(
            os.getenv("SLSKD_RETRY_BACKOFF_BASE_MS"),
            default=DEFAULT_SLSKD_RETRY_BACKOFF_BASE_MS,
        ),
    )
    retry_jitter_pct_raw = _as_float(
        os.getenv("SLSKD_JITTER_PCT"), default=DEFAULT_SLSKD_RETRY_JITTER_PCT
    )
    retry_jitter_pct = min(100.0, max(0.0, retry_jitter_pct_raw))
    preferred_formats_list = _parse_list(os.getenv("SLSKD_PREFERRED_FORMATS"))
    if not preferred_formats_list:
        preferred_formats_list = list(DEFAULT_SLSKD_PREFERRED_FORMATS)
    preferred_formats = tuple(preferred_formats_list)
    max_results = max(
        1,
        _as_int(
            os.getenv("SLSKD_MAX_RESULTS"),
            default=DEFAULT_SLSKD_MAX_RESULTS,
        ),
    )
    soulseek = SoulseekConfig(
        base_url=_resolve_setting(
            "SLSKD_URL",
            db_settings=db_settings,
            fallback=soulseek_base_env,
        )
        or DEFAULT_SOULSEEK_URL,
        api_key=_resolve_setting(
            "SLSKD_API_KEY",
            db_settings=db_settings,
            fallback=os.getenv("SLSKD_API_KEY"),
        ),
        timeout_ms=timeout_ms,
        retry_max=retry_max,
        retry_backoff_base_ms=retry_backoff_base_ms,
        retry_jitter_pct=retry_jitter_pct,
        preferred_formats=preferred_formats,
        max_results=max_results,
    )

    logging = LoggingConfig(level=os.getenv("HARMONY_LOG_LEVEL", "INFO"))
    database = DatabaseConfig(url=database_url)

    artwork_dir = os.getenv("ARTWORK_DIR") or os.getenv("HARMONY_ARTWORK_DIR")
    timeout_value = os.getenv("ARTWORK_HTTP_TIMEOUT") or os.getenv("ARTWORK_TIMEOUT_SEC")
    concurrency_value = os.getenv("ARTWORK_WORKER_CONCURRENCY") or os.getenv("ARTWORK_CONCURRENCY")
    min_edge_value = os.getenv("ARTWORK_MIN_EDGE")
    min_bytes_value = os.getenv("ARTWORK_MIN_BYTES")
    post_processors_raw = os.getenv("ARTWORK_POST_PROCESSORS")
    if post_processors_raw:
        processor_entries = post_processors_raw.replace("\n", ",").split(",")
        post_processors = tuple(
            entry.strip() for entry in processor_entries if entry.strip()
        )
    else:
        post_processors = ()

    artwork_config = ArtworkConfig(
        directory=(artwork_dir or DEFAULT_ARTWORK_DIR),
        timeout_seconds=_as_float(timeout_value, default=DEFAULT_ARTWORK_TIMEOUT),
        max_bytes=_as_int(os.getenv("ARTWORK_MAX_BYTES"), default=DEFAULT_ARTWORK_MAX_BYTES),
        concurrency=max(
            1,
            _as_int(
                concurrency_value,
                default=DEFAULT_ARTWORK_CONCURRENCY,
            ),
        ),
        min_edge=_as_int(min_edge_value, default=DEFAULT_ARTWORK_MIN_EDGE),
        min_bytes=_as_int(min_bytes_value, default=DEFAULT_ARTWORK_MIN_BYTES),
        fallback=ArtworkFallbackConfig(
            enabled=_as_bool(os.getenv("ARTWORK_FALLBACK_ENABLED"), default=False),
            provider=(os.getenv("ARTWORK_FALLBACK_PROVIDER") or "musicbrainz"),
            timeout_seconds=_as_float(
                os.getenv("ARTWORK_FALLBACK_TIMEOUT_SEC"),
                default=DEFAULT_ARTWORK_FALLBACK_TIMEOUT,
            ),
            max_bytes=_as_int(
                os.getenv("ARTWORK_FALLBACK_MAX_BYTES"),
                default=DEFAULT_ARTWORK_FALLBACK_MAX_BYTES,
            ),
        ),
        post_processing=ArtworkPostProcessingConfig(
            enabled=_as_bool(
                os.getenv("ARTWORK_POST_PROCESSING_ENABLED"),
                default=False,
            ),
            hooks=post_processors,
        ),
    )

    ingest = IngestConfig(
        batch_size=max(
            1,
            _as_int(
                os.getenv("INGEST_BATCH_SIZE"),
                default=DEFAULT_INGEST_BATCH_SIZE,
            ),
        ),
        max_pending_jobs=max(
            1,
            _as_int(
                os.getenv("INGEST_MAX_PENDING_JOBS"),
                default=DEFAULT_INGEST_MAX_PENDING_JOBS,
            ),
        ),
    )

    free_ingest = FreeIngestConfig(
        max_playlists=max(
            1,
            _as_int(
                os.getenv("FREE_MAX_PLAYLISTS"),
                default=DEFAULT_FREE_INGEST_MAX_PLAYLISTS,
            ),
        ),
        max_tracks=max(
            1,
            _as_int(
                os.getenv("FREE_MAX_TRACKS_PER_REQUEST"),
                default=DEFAULT_FREE_INGEST_MAX_TRACKS,
            ),
        ),
        batch_size=max(
            1,
            _as_int(
                os.getenv("FREE_BATCH_SIZE"),
                default=DEFAULT_FREE_INGEST_BATCH_SIZE,
            ),
        ),
    )

    api_base_path = _normalise_base_path(os.getenv("API_BASE_PATH"))

    features = FeatureFlags(
        enable_artwork=_as_bool(
            _resolve_setting(
                "ENABLE_ARTWORK",
                db_settings=db_settings,
                fallback=os.getenv("ENABLE_ARTWORK"),
            ),
            default=False,
        ),
        enable_lyrics=_as_bool(
            _resolve_setting(
                "ENABLE_LYRICS",
                db_settings=db_settings,
                fallback=os.getenv("ENABLE_LYRICS"),
            ),
            default=False,
        ),
        enable_legacy_routes=_as_bool(
            os.getenv("FEATURE_ENABLE_LEGACY_ROUTES"),
            default=False,
        ),
    )

    integrations = IntegrationsConfig(
        enabled=_parse_enabled_providers(os.getenv("INTEGRATIONS_ENABLED")),
        timeouts_ms=_parse_provider_timeouts(os.environ),
        max_concurrency=max(
            1,
            _as_int(
                os.getenv("PROVIDER_MAX_CONCURRENCY"),
                default=DEFAULT_PROVIDER_MAX_CONCURRENCY,
            ),
        ),
    )

    health = HealthConfig(
        db_timeout_ms=max(
            100,
            _as_int(
                os.getenv("HEALTH_DB_TIMEOUT_MS"),
                default=DEFAULT_HEALTH_DB_TIMEOUT_MS,
            ),
        ),
        dependency_timeout_ms=max(
            100,
            _as_int(
                os.getenv("HEALTH_DEP_TIMEOUT_MS"),
                default=DEFAULT_HEALTH_DEP_TIMEOUT_MS,
            ),
        ),
        dependencies=_parse_dependency_names(os.getenv("HEALTH_DEPS")),
        require_database=_as_bool(os.getenv("HEALTH_READY_REQUIRE_DB"), default=True),
    )

    concurrency_env = os.getenv("WATCHLIST_MAX_CONCURRENCY")
    if concurrency_env is None:
        concurrency_env = os.getenv("WATCHLIST_CONCURRENCY")
    max_concurrency = min(
        10,
        max(
            1,
            _as_int(
                concurrency_env,
                default=DEFAULT_WATCHLIST_MAX_CONCURRENCY,
            ),
        ),
    )

    spotify_timeout_ms = min(
        60_000,
        max(
            100,
            _as_int(
                os.getenv("WATCHLIST_SPOTIFY_TIMEOUT_MS"),
                default=DEFAULT_WATCHLIST_SPOTIFY_TIMEOUT_MS,
            ),
        ),
    )

    slskd_timeout_env = os.getenv("WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS")
    if slskd_timeout_env is None:
        slskd_timeout_env = os.getenv("WATCHLIST_SEARCH_TIMEOUT_MS")
    slskd_search_timeout_ms = min(
        60_000,
        max(
            100,
            _as_int(
                slskd_timeout_env,
                default=DEFAULT_WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS,
            ),
        ),
    )

    retry_env = os.getenv("WATCHLIST_RETRY_MAX")
    if retry_env is None:
        retry_env = os.getenv("WATCHLIST_BACKOFF_MAX_TRIES")
    retry_max = min(
        5,
        max(
            1,
            _as_int(
                retry_env,
                default=DEFAULT_WATCHLIST_RETRY_MAX,
            ),
        ),
    )

    retry_budget = min(
        20,
        max(
            1,
            _as_int(
                os.getenv("WATCHLIST_RETRY_BUDGET_PER_ARTIST"),
                default=DEFAULT_WATCHLIST_RETRY_BUDGET_PER_ARTIST,
            ),
        ),
    )

    cooldown_minutes = min(
        240,
        max(
            0,
            _as_int(
                os.getenv("WATCHLIST_COOLDOWN_MINUTES"),
                default=DEFAULT_WATCHLIST_COOLDOWN_MINUTES,
            ),
        ),
    )

    db_io_mode_raw = (
        (os.getenv("WATCHLIST_DB_IO_MODE") or DEFAULT_WATCHLIST_DB_IO_MODE).strip().lower()
    )
    db_io_mode = "async" if db_io_mode_raw == "async" else "thread"

    watchlist_config = WatchlistWorkerConfig(
        max_concurrency=max_concurrency,
        max_per_tick=min(
            100,
            max(
                1,
                _as_int(
                    os.getenv("WATCHLIST_MAX_PER_TICK"),
                    default=DEFAULT_WATCHLIST_MAX_PER_TICK,
                ),
            ),
        ),
        spotify_timeout_ms=spotify_timeout_ms,
        slskd_search_timeout_ms=slskd_search_timeout_ms,
        tick_budget_ms=max(
            100,
            _as_int(
                os.getenv("WATCHLIST_TICK_BUDGET_MS"),
                default=DEFAULT_WATCHLIST_TICK_BUDGET_MS,
            ),
        ),
        backoff_base_ms=min(
            5_000,
            max(
                0,
                _as_int(
                    os.getenv("WATCHLIST_BACKOFF_BASE_MS"),
                    default=DEFAULT_WATCHLIST_BACKOFF_BASE_MS,
                ),
            ),
        ),
        retry_max=retry_max,
        jitter_pct=min(
            1.0,
            max(
                0.0,
                _as_float(
                    os.getenv("WATCHLIST_JITTER_PCT"),
                    default=DEFAULT_WATCHLIST_JITTER_PCT,
                ),
            ),
        ),
        shutdown_grace_ms=max(
            0,
            _as_int(
                os.getenv("WATCHLIST_SHUTDOWN_GRACE_MS"),
                default=DEFAULT_WATCHLIST_SHUTDOWN_GRACE_MS,
            ),
        ),
        db_io_mode=db_io_mode,
        retry_budget_per_artist=retry_budget,
        cooldown_minutes=cooldown_minutes,
    )

    matching_config = load_matching_config()

    raw_env_keys = _parse_list(os.getenv("HARMONY_API_KEYS"))
    file_keys = _read_api_keys_from_file(os.getenv("HARMONY_API_KEYS_FILE", ""))
    api_keys = _deduplicate_preserve_order(key.strip() for key in [*raw_env_keys, *file_keys])

    default_allowlist = [
        _compose_allowlist_entry(api_base_path, suffix) for suffix in DEFAULT_ALLOWLIST_SUFFIXES
    ]
    allowlist_override_entries = [
        _normalise_prefix(entry) for entry in _parse_list(os.getenv("AUTH_ALLOWLIST"))
    ]
    allowlist_entries = _deduplicate_preserve_order(
        entry for entry in [*default_allowlist, *allowlist_override_entries] if entry
    )

    request_id_config = RequestMiddlewareConfig(
        header_name=(os.getenv("REQUEST_ID_HEADER") or "X-Request-ID").strip() or "X-Request-ID"
    )

    security_profile, security_defaults = _resolve_security_profile(os.environ)
    require_auth_override = _parse_bool_override(os.getenv("FEATURE_REQUIRE_AUTH"))
    rate_limit_override = _parse_bool_override(os.getenv("FEATURE_RATE_LIMITING"))
    rate_limit_enabled = (
        security_defaults.rate_limiting
        if rate_limit_override is None
        else rate_limit_override
    )

    rate_limit_config = RateLimitMiddlewareConfig(
        enabled=rate_limit_enabled,
        bucket_capacity=max(1, _as_int(os.getenv("RATE_LIMIT_BUCKET_CAP"), default=60)),
        refill_per_second=_bounded_float(
            os.getenv("RATE_LIMIT_REFILL_PER_SEC"),
            default=1.0,
            minimum=0.0,
        ),
    )

    cacheable_paths_env = _parse_list(os.getenv("CACHEABLE_PATHS"))
    merged_cacheable_paths = _deduplicate_preserve_order(
        [*cacheable_paths_env, *DEFAULT_CACHEABLE_PATH_PATTERNS]
    )
    cache_rules = _parse_cache_rules(merged_cacheable_paths)
    cache_config = CacheMiddlewareConfig(
        enabled=_as_bool(os.getenv("CACHE_ENABLED"), default=True),
        default_ttl=max(0, _as_int(os.getenv("CACHE_DEFAULT_TTL_S"), default=30)),
        max_items=max(1, _as_int(os.getenv("CACHE_MAX_ITEMS"), default=5_000)),
        etag_strategy=(os.getenv("CACHE_STRATEGY_ETAG") or "strong").strip().lower() or "strong",
        fail_open=_as_bool(os.getenv("CACHE_FAIL_OPEN"), default=True),
        stale_while_revalidate=_parse_optional_duration(
            (os.getenv("CACHE_STALE_WHILE_REVALIDATE_S") or "").strip() or None
        ),
        cacheable_paths=cache_rules,
    )

    cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS")
    if cors_origins_env is None:
        cors_origins_env = os.getenv("ALLOWED_ORIGINS")
    cors_origins = _parse_list(cors_origins_env)
    if not cors_origins:
        cors_origins = ["*"]
    cors_headers = _parse_list(os.getenv("CORS_ALLOWED_HEADERS")) or ["*"]
    cors_methods = _parse_list(os.getenv("CORS_ALLOWED_METHODS")) or [
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ]
    cors_config = CorsMiddlewareConfig(
        allowed_origins=_deduplicate_preserve_order(cors_origins),
        allowed_headers=_deduplicate_preserve_order(cors_headers),
        allowed_methods=_deduplicate_preserve_order(cors_methods),
    )

    gzip_config = GZipMiddlewareConfig(
        min_size=max(0, _as_int(os.getenv("GZIP_MIN_SIZE"), default=1_024)),
    )

    middleware_config = MiddlewareConfig(
        request_id=request_id_config,
        rate_limit=rate_limit_config,
        cache=cache_config,
        cors=cors_config,
        gzip=gzip_config,
    )

    security = SecurityConfig(
        profile=security_profile,
        api_keys=api_keys,
        allowlist=allowlist_entries,
        allowed_origins=middleware_config.cors.allowed_origins,
        _require_auth_default=security_defaults.require_auth,
        _rate_limiting_default=security_defaults.rate_limiting,
        _require_auth_override=require_auth_override,
        _rate_limiting_override=rate_limit_override,
    )

    return AppConfig(
        spotify=spotify,
        soulseek=soulseek,
        logging=logging,
        database=database,
        artwork=artwork_config,
        ingest=ingest,
        free_ingest=free_ingest,
        features=features,
        integrations=integrations,
        security=security,
        middleware=middleware_config,
        api_base_path=api_base_path,
        health=health,
        watchlist=watchlist_config,
        matching=matching_config,
        environment=environment_config,
    )


def is_feature_enabled(
    name: str,
    *,
    config: AppConfig | None = None,
    database_url: Optional[str] = None,
) -> bool:
    """Return the enabled state for the requested feature flag."""

    normalized = name.strip().lower()
    feature_key_map = {
        "artwork": "ENABLE_ARTWORK",
        "lyrics": "ENABLE_LYRICS",
    }
    try:
        key = feature_key_map[normalized]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Unknown feature flag: {name}") from exc

    if config is not None:
        features = config.features
        if normalized == "artwork":
            return features.enable_artwork
        if normalized == "lyrics":
            return features.enable_lyrics

    db_value = get_setting(key, database_url=database_url)
    if db_value is not None:
        return _as_bool(db_value, default=False)

    return _as_bool(os.getenv(key), default=False)
