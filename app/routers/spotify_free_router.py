"""Compatibility shim delegating to :mod:`app.api.spotify` FREE router."""

from __future__ import annotations

from warnings import warn

from app.api.spotify import free_router as router

warn(
    "app.routers.spotify_free_router is deprecated; use app.api.spotify.free_router instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["router"]
