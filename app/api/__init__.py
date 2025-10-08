"""Public API helpers for router registration and error handling."""

from . import artists, router_registry, search, spotify, system
from .errors import setup_exception_handlers

__all__ = [
    "artists",
    "router_registry",
    "search",
    "spotify",
    "system",
    "setup_exception_handlers",
]
