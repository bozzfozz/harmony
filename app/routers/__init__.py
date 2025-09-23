"""Expose API routers."""
from .beets_router import router as beets_router
from .matching_router import router as matching_router
from .plex_router import router as plex_router
from .settings_router import router as settings_router
from .soulseek_router import router as soulseek_router
from .spotify_router import router as spotify_router

__all__ = [
    "beets_router",
    "matching_router",
    "plex_router",
    "settings_router",
    "soulseek_router",
    "spotify_router",
]
