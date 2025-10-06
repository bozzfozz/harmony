"""Compatibility shim re-exporting the unified Spotify router."""

from __future__ import annotations

from app.api.spotify import core_router as router
from app.routers._deprecation import emit_router_deprecation

emit_router_deprecation(
    "app.routers.spotify_router",
    "app.api.spotify.core_router",
)

__all__ = ["router"]
