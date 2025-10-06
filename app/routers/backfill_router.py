"""Compatibility layer delegating to the unified Spotify backfill router."""

from __future__ import annotations

from app.api.spotify import backfill_router as router
from app.routers._deprecation import emit_router_deprecation

emit_router_deprecation(
    "app.routers.backfill_router",
    "app.api.spotify.backfill_router",
)

__all__ = ["router"]
