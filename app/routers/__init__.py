from .activity_router import router as activity_router
from .beets_router import router as beets_router
from .download_router import router as download_router
from .health_router import router as health_router
from .matching_router import router as matching_router
from .metadata_router import router as metadata_router
from .plex_router import router as plex_router
from .search_router import router as search_router
from .settings_router import router as settings_router
from .soulseek_router import router as soulseek_router
from .spotify_router import router as spotify_router
from .sync_router import router as sync_router
from .watchlist_router import router as watchlist_router
from .system_router import router as system_router

__all__ = [
    "activity_router",
    "beets_router",
    "download_router",
    "health_router",
    "matching_router",
    "metadata_router",
    "search_router",
    "plex_router",
    "settings_router",
    "soulseek_router",
    "spotify_router",
    "sync_router",
    "system_router",
    "watchlist_router",
]
