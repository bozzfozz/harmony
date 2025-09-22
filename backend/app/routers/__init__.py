"""Router exports for the backend package."""

from . import matching_router, plex_router, spotify_router, sync_router

__all__ = ["plex_router", "spotify_router", "matching_router", "sync_router"]
