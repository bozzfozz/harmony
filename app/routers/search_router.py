"""Compatibility shim delegating to :mod:`app.api.routers.search`."""

from __future__ import annotations

from app.api.routers.search import log_event, router
from app.routers._deprecation import emit_router_deprecation

emit_router_deprecation(
    "app.routers.search_router",
    "app.api.routers.search.router",
)

__all__ = ["router", "log_event"]
