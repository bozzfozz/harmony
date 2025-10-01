"""Compatibility shim for the unified Spotify FREE ingest router."""

from __future__ import annotations

from warnings import warn

from app.api.spotify import free_ingest_router as router

warn(
    "app.routers.free_ingest_router is deprecated; use app.api.spotify.free_ingest_router instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["router"]
