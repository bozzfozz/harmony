"""Compatibility shim delegating to :mod:`app.api.routers.watchlist`."""

from __future__ import annotations

from warnings import warn

from app.api.routers.watchlist import router

warn(
    "app.routers.watchlist_router is deprecated; use app.api.routers.watchlist.router instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["router"]
