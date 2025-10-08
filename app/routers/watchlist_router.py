"""Compatibility shim delegating to :mod:`app.api.routers.watchlist`."""

from __future__ import annotations

from app.api._deprecation import warn_legacy_import
from app.api.routers.watchlist import router

warn_legacy_import(
    "app.routers.watchlist_router",
    "app.api.routers.watchlist.router",
)

__all__ = ["router"]
