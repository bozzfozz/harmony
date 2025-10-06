"""Compatibility shim delegating to :mod:`app.api.spotify` FREE router."""

from __future__ import annotations

from app.api.spotify import free_router as router
from app.routers._deprecation import emit_router_deprecation

emit_router_deprecation(
    "app.routers.spotify_free_router",
    "app.api.spotify.free_router",
)

__all__ = ["router"]
