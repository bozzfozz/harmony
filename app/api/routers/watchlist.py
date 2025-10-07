"""Backward compatibility shim importing the new watchlist API router."""

from __future__ import annotations

from app.api.watchlist import router


__all__ = ["router"]

