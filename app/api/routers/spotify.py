"""Compatibility shim exposing :mod:`app.api.spotify`."""

from app.api.spotify import (backfill_router, core_router, free_ingest_router,
                             free_router, router)

__all__ = [
    "router",
    "core_router",
    "backfill_router",
    "free_router",
    "free_ingest_router",
]
