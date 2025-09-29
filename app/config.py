"""Application configuration utilities for Harmony."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


@dataclass(slots=True)
class SpotifyConfig:
    client_id: Optional[str]
    client_secret: Optional[str]
    redirect_uri: Optional[str]
    scope: str
    mode: str
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
class ArtworkConfig:
    directory: str
    timeout_seconds: float
    max_bytes: int
    concurrency: int
    min_edge: int
    min_bytes: int
    fallback: ArtworkFallbackConfig


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
class MetricsConfig:
    enabled: bool
    path: str
    require_api_key: bool


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


@dataclass(slots=True)
class MatchingConfig:
    edition_aware: bool
    fuzzy_max_candidates: int
    min_artist_similarity: float
    complete_threshold: float
    nearly_threshold: float


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
    api_base_path: str
    health: HealthConfig
    metrics: MetricsConfig
    watchlist: WatchlistWorkerConfig
    matching: MatchingConfig


@dataclass(slots=True)
class SecurityConfig:
    require_auth: bool
    api_keys: tuple[str, ...]
    allowlist: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    rate_limiting_enabled: bool


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
DEFAULT_SPOTIFY_MODE = "PRO"
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
DEFAULT_PROVIDER_MAX_CONCURRENCY = 4
DEFAULT_SLSKD_TIMEOUT_MS = 8_000
DEFAULT_SLSKD_RETRY_MAX = 3
DEFAULT_SLSKD_RETRY_BACKOFF_BASE_MS = 250
DEFAULT_SLSKD_RETRY_JITTER_PCT = 20.0
DEFAULT_SLSKD_PREFERRED_FORMATS = ("FLAC", "ALAC", "APE", "MP3")
DEFAULT_SLSKD_MAX_RESULTS = 50
DEFAULT_HEALTH_DB_TIMEOUT_MS = 500
DEFAULT_HEALTH_DEP_TIMEOUT_MS = 800
DEFAULT_METRICS_PATH = "/metrics"
DEFAULT_WATCHLIST_MAX_CONCURRENCY = 3
DEFAULT_WATCHLIST_MAX_PER_TICK = 20
DEFAULT_WATCHLIST_SPOTIFY_TIMEOUT_MS = 8_000
DEFAULT_WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS = 12_000
DEFAULT_WATCHLIST_TICK_BUDGET_MS = 8_000
DEFAULT_WATCHLIST_BACKOFF_BASE_MS = 250
DEFAULT_WATCHLIST_RETRY_MAX = 3
DEFAULT_WATCHLIST_JITTER_PCT = 0.2
DEFAULT_WATCHLIST_SHUTDOWN_GRACE_MS = 2_000
DEFAULT_WATCHLIST_DB_IO_MODE = "thread"
DEFAULT_WATCHLIST_RETRY_BUDGET_PER_ARTIST = 6
DEFAULT_WATCHLIST_COOLDOWN_MINUTES = 15
DEFAULT_MATCH_FUZZY_MAX_CANDIDATES = 50
DEFAULT_MATCH_MIN_ARTIST_SIM = 0.6
DEFAULT_MATCH_COMPLETE_THRESHOLD = 0.9
DEFAULT_MATCH_NEARLY_THRESHOLD = 0.8


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


def _parse_list(value: Optional[str]) -> list[str]:
    if value is None:
        return []
    candidates = value.replace("\n", ",").split(",")
    return [item.strip() for item in candidates if item.strip()]


def _parse_enabled_providers(value: Optional[str]) -> tuple[str, ...]:
    if not value:
        return ("spotify",)
    items = [entry.strip().lower() for entry in value.replace("\n", ",").split(",")]
    deduplicated: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            deduplicated.append(item)
    return tuple(deduplicated or ("spotify",))


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


def _normalise_metrics_path(value: Optional[str]) -> str:
    candidate = (value or DEFAULT_METRICS_PATH).strip()
    if not candidate:
        candidate = DEFAULT_METRICS_PATH
    if not candidate.startswith("/"):
        candidate = f"/{candidate}"
    if candidate != "/":
        candidate = candidate.rstrip("/")
    return candidate or DEFAULT_METRICS_PATH


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


def _normalise_mode(value: Optional[str]) -> str:
    candidate = (value or "").strip().upper()
    if candidate not in {"FREE", "PRO"}:
        return DEFAULT_SPOTIFY_MODE
    return candidate


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
        "SPOTIFY_MODE",
        "ENABLE_ARTWORK",
        "ENABLE_LYRICS",
    ]
    db_settings = dict(_load_settings_from_db(config_keys, database_url=database_url))
    legacy_slskd_url = _legacy_slskd_url()
    if legacy_slskd_url is not None:
        db_settings.pop("SLSKD_URL", None)

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
        mode=_normalise_mode(
            _resolve_setting(
                "SPOTIFY_MODE",
                db_settings=db_settings,
                fallback=os.getenv("SPOTIFY_MODE"),
            )
        ),
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

    metrics_path = _normalise_metrics_path(os.getenv("METRICS_PATH"))
    metrics = MetricsConfig(
        enabled=_as_bool(os.getenv("FEATURE_METRICS_ENABLED"), default=False),
        path=metrics_path,
        require_api_key=_as_bool(os.getenv("METRICS_REQUIRE_API_KEY"), default=True),
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
    if not metrics.require_api_key:
        metrics_prefix = _normalise_prefix(metrics.path)
        allowlist_entries = _deduplicate_preserve_order((*allowlist_entries, metrics_prefix))
    allowed_origins = _deduplicate_preserve_order(_parse_list(os.getenv("ALLOWED_ORIGINS")))

    security = SecurityConfig(
        require_auth=_as_bool(os.getenv("FEATURE_REQUIRE_AUTH"), default=False),
        api_keys=api_keys,
        allowlist=allowlist_entries,
        allowed_origins=allowed_origins,
        rate_limiting_enabled=_as_bool(
            os.getenv("FEATURE_RATE_LIMITING"),
            default=False,
        ),
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
        api_base_path=api_base_path,
        health=health,
        metrics=metrics,
        watchlist=watchlist_config,
        matching=matching_config,
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
