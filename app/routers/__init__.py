"""Expose API routers."""
from .matching_router import router as matching_router
from .plex_router import router as plex_router
from .settings_router import router as settings_router
from .soulseek_router import router as soulseek_router
from .spotify_router import router as spotify_router

__all__ = [
    "matching_router",
    "plex_router",
    "settings_router",
    "soulseek_router",
    "spotify_router",
]
