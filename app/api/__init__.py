"""Public API helpers for router registration and error handling."""

from .errors import setup_exception_handlers
from . import router_registry, routers

__all__ = [
    "router_registry",
    "routers",
    "setup_exception_handlers",
]
