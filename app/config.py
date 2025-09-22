"""Application configuration utilities for Harmony."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class SpotifyConfig:
    client_id: Optional[str]
    client_secret: Optional[str]
    redirect_uri: Optional[str]
    scope: str


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
class AppConfig:
    spotify: SpotifyConfig
    plex: PlexConfig
    soulseek: SoulseekConfig
    logging: LoggingConfig
    database: DatabaseConfig


DEFAULT_DB_URL = "sqlite:///./harmony.db"
DEFAULT_SOULSEEK_URL = "http://localhost:5030"
DEFAULT_SPOTIFY_SCOPE = (
    "user-library-read playlist-read-private playlist-read-collaborative"
)


def load_config() -> AppConfig:
    """Load application configuration from environment variables."""

    spotify = SpotifyConfig(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope=os.getenv("SPOTIFY_SCOPE", DEFAULT_SPOTIFY_SCOPE),
    )

    plex = PlexConfig(
        base_url=os.getenv("PLEX_BASE_URL") or os.getenv("PLEX_URL"),
        token=os.getenv("PLEX_TOKEN"),
        library_name=os.getenv("PLEX_LIBRARY"),
    )

    soulseek = SoulseekConfig(
        base_url=os.getenv("SLSKD_URL", DEFAULT_SOULSEEK_URL),
        api_key=os.getenv("SLSKD_API_KEY"),
    )

    logging = LoggingConfig(level=os.getenv("HARMONY_LOG_LEVEL", "INFO"))
    database = DatabaseConfig(url=os.getenv("DATABASE_URL", DEFAULT_DB_URL))

    return AppConfig(
        spotify=spotify,
        plex=plex,
        soulseek=soulseek,
        logging=logging,
        database=database,
    )
