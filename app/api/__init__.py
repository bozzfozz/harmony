"""Public API helpers for router registration and error handling."""

from .errors import setup_exception_handlers
from . import artists, router_registry, search, spotify, system

__all__ = [
    "artists",
    "router_registry",
    "search",
    "spotify",
    "system",
    "setup_exception_handlers",
]
