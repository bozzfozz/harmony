"""Compatibility shim delegating to :mod:`app.api.routers.system`."""

from __future__ import annotations

from app.api._deprecation import warn_legacy_import
from app.api.routers.system import psutil, router

warn_legacy_import(
    "app.routers.system_router",
    "app.api.routers.system.router",
)

__all__ = ["router", "psutil"]
