"""Public API helpers for router registration, middleware and error handling."""

from .errors import setup_exception_handlers
from .middleware import install_api_middlewares
from . import router_registry, routers

__all__ = [
    "install_api_middlewares",
    "router_registry",
    "routers",
    "setup_exception_handlers",
]
