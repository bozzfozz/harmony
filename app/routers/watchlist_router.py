"""Compatibility shim delegating to :mod:`app.api.routers.watchlist`."""

from __future__ import annotations

from app.api.routers.watchlist import router
from app.routers._deprecation import emit_router_deprecation

emit_router_deprecation(
    "app.routers.watchlist_router",
    "app.api.routers.watchlist.router",
)

__all__ = ["router"]
