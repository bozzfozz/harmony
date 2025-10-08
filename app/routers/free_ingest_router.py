"""Compatibility shim for the unified Spotify FREE ingest router."""

from __future__ import annotations

from app._legacy import warn_legacy_import
from app.api.routers.spotify import free_ingest_router as router

warn_legacy_import(
    "app.routers.free_ingest_router",
    "app.api.routers.spotify.free_ingest_router",
)

__all__ = ["router"]
