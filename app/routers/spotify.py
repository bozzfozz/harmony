"""Backward-compatible re-export for the unified Spotify router."""

from app.api.spotify import legacy_router, router

__all__ = ["router", "legacy_router"]
