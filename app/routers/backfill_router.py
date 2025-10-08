"""Compatibility layer delegating to the unified Spotify backfill router."""

from __future__ import annotations

from app._legacy import warn_legacy_import
from app.api.routers.spotify import backfill_router as router

warn_legacy_import(
    "app.routers.backfill_router",
    "app.api.routers.spotify.backfill_router",
)

__all__ = ["router"]
