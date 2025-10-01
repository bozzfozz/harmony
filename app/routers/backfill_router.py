"""Compatibility layer delegating to the unified Spotify backfill router."""

from __future__ import annotations

from warnings import warn

from app.api.spotify import backfill_router as router

warn(
    "app.routers.backfill_router is deprecated; use app.api.spotify.backfill_router instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["router"]
