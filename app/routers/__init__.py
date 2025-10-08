from importlib import import_module
from typing import Any

from ._deprecation import emit_router_deprecation
from .activity_router import router as activity_router
from .dlq_router import router as dlq_router
from .download_router import router as download_router
from .health_router import router as health_router
from .imports_router import router as imports_router
from .integrations import router as integrations_router
from .matching_router import router as matching_router
from .metadata_router import router as metadata_router
from .settings_router import router as settings_router
from .soulseek_router import router as soulseek_router
from .sync_router import router as sync_router

_DEPRECATED_EXPORTS: dict[str, tuple[str, str]] = {
    "search_router": ("app.api.routers.search", "router"),
    "system_router": ("app.api.routers.system", "router"),
    "watchlist_router": ("app.api.routers.watchlist", "router"),
}

__all__ = [
    "activity_router",
    "download_router",
    "dlq_router",
    "health_router",
    "imports_router",
    "integrations_router",
    "matching_router",
    "metadata_router",
    "settings_router",
    "soulseek_router",
    "sync_router",
    "search_router",
    "system_router",
    "watchlist_router",
]


def __getattr__(name: str) -> Any:
    if name in _DEPRECATED_EXPORTS:
        module_path, attribute = _DEPRECATED_EXPORTS[name]
        emit_router_deprecation(
            f"app.routers.{name}",
            f"{module_path}.{attribute}",
            stacklevel=3,
        )
        module = import_module(module_path)
        value = getattr(module, attribute)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'app.routers' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__))
