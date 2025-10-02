"""Compatibility layer exposing Spotify domain routers from :mod:`app.api.routers`."""

from .routers.spotify import (
    backfill_router,
    core_router,
    free_ingest_router,
    free_router,
    legacy_router,
    router,
)

__all__ = [
    "router",
    "core_router",
    "backfill_router",
    "free_router",
    "free_ingest_router",
    "legacy_router",
]
