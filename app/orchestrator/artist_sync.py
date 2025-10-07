"""Compatibility layer exporting artist sync orchestration helpers."""

from __future__ import annotations

from .handlers_artist import (
    ArtistSyncHandlerDeps,
    build_artist_sync_handler,
    enqueue_artist_sync,
    handle_artist_sync,
)

__all__ = [
    "ArtistSyncHandlerDeps",
    "build_artist_sync_handler",
    "enqueue_artist_sync",
    "handle_artist_sync",
]
