"""FastAPI dependency providers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Generator

from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.core.matching_engine import MusicMatchingEngine
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.core.transfers_api import TransfersApi
from app.db import get_session


@lru_cache()
def get_app_config() -> AppConfig:
    return load_config()


@lru_cache()
def get_spotify_client() -> SpotifyClient:
    return SpotifyClient(get_app_config().spotify)


@lru_cache()
def get_plex_client() -> Any:
    raise ValueError("Plex integration is disabled in the MVP build")


@lru_cache()
def get_soulseek_client() -> SoulseekClient:
    return SoulseekClient(get_app_config().soulseek)


@lru_cache()
def get_transfers_api() -> TransfersApi:
    return TransfersApi(get_soulseek_client())


@lru_cache()
def get_matching_engine() -> MusicMatchingEngine:
    return MusicMatchingEngine()


def get_db() -> Generator[Session, None, None]:
    session = get_session()
    try:
        yield session
    finally:
        session.close()
