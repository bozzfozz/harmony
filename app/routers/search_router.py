"""Compatibility shim delegating to :mod:`app.api.routers.search`."""

from __future__ import annotations

from warnings import warn

from app.api.routers.search import log_event, router

warn(
    "app.routers.search_router is deprecated; use app.api.routers.search.router instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["router", "log_event"]
