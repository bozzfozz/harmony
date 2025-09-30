from .activity_router import router as activity_router
from .download_router import router as download_router
from .dlq_router import router as dlq_router
from .health_router import router as health_router
from .imports_router import router as imports_router
from .integrations import router as integrations_router
from .matching_router import router as matching_router
from .metadata_router import router as metadata_router
from .search_router import router as search_router
from .settings_router import router as settings_router
from .soulseek_router import router as soulseek_router
from .spotify import legacy_router as spotify_legacy_router
from .spotify import router as spotify_domain_router
from .sync_router import router as sync_router
from .watchlist_router import router as watchlist_router
from .system_router import router as system_router

__all__ = [
    "activity_router",
    "download_router",
    "dlq_router",
    "health_router",
    "imports_router",
    "integrations_router",
    "matching_router",
    "metadata_router",
    "search_router",
    "settings_router",
    "soulseek_router",
    "spotify_domain_router",
    "spotify_legacy_router",
    "sync_router",
    "system_router",
    "watchlist_router",
]
