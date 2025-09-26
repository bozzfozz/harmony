"""Application configuration utilities for Harmony."""

from __future__ import annotations

import os
from dataclasses import dataclass
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
class PlexConfig:
    base_url: Optional[str]
    token: Optional[str]
    library_name: Optional[str]


@dataclass(slots=True)
class SoulseekConfig:
    base_url: str
    api_key: Optional[str]


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
    poststep_enabled: bool


@dataclass(slots=True)
class FreeIngestConfig:
    max_playlists: int
    max_tracks: int
    batch_size: int


@dataclass(slots=True)
class AppConfig:
    spotify: SpotifyConfig
    plex: PlexConfig
    soulseek: SoulseekConfig
    logging: LoggingConfig
    database: DatabaseConfig
    artwork: ArtworkConfig
    free_ingest: FreeIngestConfig


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
DEFAULT_BACKFILL_MAX_ITEMS = 2_000
DEFAULT_BACKFILL_CACHE_TTL = 604_800


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


def _as_float(value: Optional[str], *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
        "PLEX_BASE_URL",
        "PLEX_TOKEN",
        "PLEX_LIBRARY",
        "SLSKD_URL",
        "SLSKD_API_KEY",
        "BEETS_POSTSTEP_ENABLED",
        "SPOTIFY_MODE",
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

    plex_base_url_env = os.getenv("PLEX_BASE_URL") or os.getenv("PLEX_URL")
    plex = PlexConfig(
        base_url=_resolve_setting(
            "PLEX_BASE_URL",
            db_settings=db_settings,
            fallback=plex_base_url_env,
        ),
        token=_resolve_setting(
            "PLEX_TOKEN",
            db_settings=db_settings,
            fallback=os.getenv("PLEX_TOKEN"),
        ),
        library_name=_resolve_setting(
            "PLEX_LIBRARY",
            db_settings=db_settings,
            fallback=os.getenv("PLEX_LIBRARY"),
        ),
    )

    soulseek_base_env = os.getenv("SLSKD_URL") or legacy_slskd_url or DEFAULT_SOULSEEK_URL
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
    )

    logging = LoggingConfig(level=os.getenv("HARMONY_LOG_LEVEL", "INFO"))
    database = DatabaseConfig(url=database_url)

    artwork_dir = os.getenv("ARTWORK_DIR") or os.getenv("HARMONY_ARTWORK_DIR")
    timeout_value = os.getenv("ARTWORK_HTTP_TIMEOUT") or os.getenv("ARTWORK_TIMEOUT_SEC")
    concurrency_value = os.getenv("ARTWORK_WORKER_CONCURRENCY") or os.getenv("ARTWORK_CONCURRENCY")
    min_edge_value = os.getenv("ARTWORK_MIN_EDGE")
    min_bytes_value = os.getenv("ARTWORK_MIN_BYTES")
    beets_env_value = os.getenv("BEETS_POSTSTEP_ENABLED")
    beets_setting_raw = _resolve_setting(
        "BEETS_POSTSTEP_ENABLED",
        db_settings=db_settings,
        fallback=beets_env_value,
    )
    beets_default = _as_bool(beets_env_value, default=False)
    beets_poststep_enabled = _as_bool(beets_setting_raw, default=beets_default)
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
        poststep_enabled=beets_poststep_enabled,
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

    return AppConfig(
        spotify=spotify,
        plex=plex,
        soulseek=soulseek,
        logging=logging,
        database=database,
        artwork=artwork_config,
        free_ingest=free_ingest,
    )
