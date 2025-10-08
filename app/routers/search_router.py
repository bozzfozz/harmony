"""Compatibility shim delegating to :mod:`app.api.routers.search`."""

from __future__ import annotations

from app.api._deprecation import warn_legacy_import
from app.api.routers.search import log_event, router

warn_legacy_import(
    "app.routers.search_router",
    "app.api.routers.search.router",
)

__all__ = ["router", "log_event"]
