"""Compatibility tests for the public Plex router import path."""

from __future__ import annotations

from app.routers import plex_router as public_router
from backend.app.routers import plex_router as backend_router


def test_public_router_aliases_backend_router() -> None:
    """The legacy app package exposes the backend Plex router module."""

    assert public_router is backend_router
