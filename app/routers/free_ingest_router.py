"""Compatibility shim for the unified Spotify FREE ingest router."""

from __future__ import annotations

from app.api.spotify import free_ingest_router as router
from app.routers._deprecation import emit_router_deprecation

emit_router_deprecation(
    "app.routers.free_ingest_router",
    "app.api.spotify.free_ingest_router",
)

__all__ = ["router"]
