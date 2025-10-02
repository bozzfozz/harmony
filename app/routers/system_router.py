"""Compatibility shim delegating to :mod:`app.api.routers.system`."""

from __future__ import annotations

from warnings import warn

from app.api.routers.system import psutil, router

warn(
    "app.routers.system_router is deprecated; use app.api.routers.system.router instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["router", "psutil"]
