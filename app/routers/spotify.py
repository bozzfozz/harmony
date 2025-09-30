"""Aggregate Spotify related routers under a single module."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import load_config
from app.routers.backfill_router import router as backfill_router
from app.routers.free_ingest_router import router as free_ingest_router
from app.routers.spotify_free_router import router as spotify_free_router
from app.routers.spotify_router import router as core_router

router = APIRouter()
router.include_router(core_router, prefix="/spotify", tags=["Spotify"])
router.include_router(backfill_router, prefix="/spotify/backfill", tags=["Spotify Backfill"])
router.include_router(spotify_free_router)
router.include_router(free_ingest_router)

_config = load_config()
_legacy_router: APIRouter | None = None
if _config.features.enable_legacy_routes:
    alias = APIRouter()
    alias.include_router(core_router, prefix="/spotify", tags=["Spotify"])
    alias.include_router(backfill_router, prefix="/spotify/backfill", tags=["Spotify Backfill"])
    alias.include_router(spotify_free_router)
    alias.include_router(free_ingest_router)
    _legacy_router = alias

legacy_router = _legacy_router

__all__ = [
    "router",
    "legacy_router",
]
