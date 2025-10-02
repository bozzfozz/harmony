"""Compatibility shim exposing :mod:`app.api.search`."""

from app.api.search import log_event, router

__all__ = ["router", "log_event"]
