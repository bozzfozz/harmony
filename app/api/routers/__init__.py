"""Domain-specific FastAPI routers for the public API."""

from .spotify import router as spotify_router
from .search import router as search_router
from .watchlist import router as watchlist_router
from .system import router as system_router

__all__ = [
    "spotify_router",
    "search_router",
    "watchlist_router",
    "system_router",
]
