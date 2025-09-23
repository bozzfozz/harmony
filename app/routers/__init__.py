"""Expose API routers."""
from .beets_router import router as beets_router
from .matching_router import router as matching_router
from .metadata_router import router as metadata_router
from .plex_router import router as plex_router
from .settings_router import router as settings_router
from .sync_router import router as sync_router
from .system_router import router as system_router
from .soulseek_router import router as soulseek_router
from .spotify_router import router as spotify_router

__all__ = [
    "beets_router",
    "matching_router",
    "metadata_router",
    "plex_router",
    "settings_router",
    "sync_router",
    "soulseek_router",
    "spotify_router",
    "system_router",
]
