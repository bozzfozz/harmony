"""Public API helpers for router registration and error handling."""

from . import artists, health, oauth_public, router_registry, search, spotify, system
from .errors import setup_exception_handlers

__all__ = [
    "artists",
    "health",
    "oauth_public",
    "router_registry",
    "search",
    "spotify",
    "system",
    "setup_exception_handlers",
]
