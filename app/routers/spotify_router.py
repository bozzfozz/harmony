"""Compatibility shim re-exporting the unified Spotify router."""

from __future__ import annotations

from app._legacy import warn_legacy_import
from app.api.routers.spotify import core_router as router

warn_legacy_import(
    "app.routers.spotify_router",
    "app.api.routers.spotify.core_router",
)

__all__ = ["router"]
