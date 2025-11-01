"""Core configuration facade for Harmony."""

from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any

from app.runtime.paths import SQLITE_DATABASE_URL

from .database import HARMONY_DATABASE_FILE, HARMONY_DATABASE_URL, get_database_url

DEFAULT_DATABASE_URL = SQLITE_DATABASE_URL

_CONFIG_EXPORT_NAMES: tuple[str, ...] = (
    "AppConfig",
    "ArtworkConfig",
    "ArtworkPostProcessingConfig",
    "CacheMiddlewareConfig",
    "CacheRule",
    "CorsMiddlewareConfig",
    "DEFAULT_DOWNLOADS_DIR",
    "DEFAULT_MUSIC_DIR",
    "DEFAULT_OAUTH_STATE_DIR",
    "DEFAULT_PLAYLIST_SYNC_STALE_AFTER",
    "DEFAULT_RETRY_BASE_SECONDS",
    "DEFAULT_RETRY_JITTER_PCT",
    "DEFAULT_RETRY_MAX_ATTEMPTS",
    "DEFAULT_RETRY_POLICY_RELOAD_S",
    "ExternalCallPolicy",
    "GZipMiddlewareConfig",
    "HdmConfig",
    "HealthConfig",
    "MatchingConfig",
    "OrchestratorConfig",
    "ProviderProfile",
    "RateLimitMiddlewareConfig",
    "SecurityConfig",
    "Settings",
    "SoulseekConfig",
    "SpotifyConfig",
    "WatchlistTimerConfig",
    "WatchlistWorkerConfig",
    "get_env",
    "get_runtime_env",
    "load_config",
    "load_matching_config",
    "load_runtime_env",
    "resolve_app_port",
    "settings",
)

_CONFIG_MODULE: ModuleType | None = None
_CONFIG_IMPL_NAME = "app._config_impl"


def _load_config_module() -> ModuleType:
    """Import the legacy ``app/config.py`` module exactly once."""

    global _CONFIG_MODULE
    if _CONFIG_MODULE is not None:
        return _CONFIG_MODULE

    config_path = Path(__file__).resolve().parent.parent / "config.py"
    spec = spec_from_file_location(_CONFIG_IMPL_NAME, config_path)
    if spec is None or spec.loader is None:
        raise ImportError("Unable to load Harmony configuration module")

    module = module_from_spec(spec)
    sys.modules.setdefault(_CONFIG_IMPL_NAME, module)
    spec.loader.exec_module(module)
    _CONFIG_MODULE = module
    return module


def __getattr__(name: str) -> Any:  # pragma: no cover - exercised indirectly
    """Forward attribute lookups to the legacy configuration module."""

    module = _load_config_module()
    try:
        value = getattr(module, name)
    except AttributeError as exc:  # pragma: no cover - defensive guard
        raise AttributeError(f"module {__name__} has no attribute {name}") from exc
    globals()[name] = value
    return value


def _export_public_api() -> None:
    module = _load_config_module()
    for attribute in _CONFIG_EXPORT_NAMES:
        globals()[attribute] = getattr(module, attribute)


_export_public_api()

__all__ = [
    "DEFAULT_DATABASE_URL",
    "HARMONY_DATABASE_FILE",
    "HARMONY_DATABASE_URL",
    "get_database_url",
    *_CONFIG_EXPORT_NAMES,
]
