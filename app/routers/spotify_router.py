"""Compatibility shim re-exporting the unified Spotify router."""

from __future__ import annotations

from warnings import warn

from app.api.spotify import core_router as router

warn(
    "app.routers.spotify_router is deprecated; use app.api.spotify.core_router instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["router"]
