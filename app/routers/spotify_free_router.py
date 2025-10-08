"""Compatibility shim delegating to :mod:`app.api.spotify` FREE router."""

from __future__ import annotations

from app.api._deprecation import warn_legacy_import
from app.api.routers.spotify import free_router as router

warn_legacy_import(
    "app.routers.spotify_free_router",
    "app.api.routers.spotify.free_router",
)

__all__ = ["router"]
