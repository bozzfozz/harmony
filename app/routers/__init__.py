from . import beets_router, matching_router, settings_router, soulseek_router, spotify_router
from backend.app.routers import plex_router, sync_router

__all__ = [
    "beets_router",
    "matching_router",
    "plex_router",
    "settings_router",
    "soulseek_router",
    "spotify_router",
    "sync_router",
]
