"""Configuration facade re-exporting the legacy Harmony settings API."""

from __future__ import annotations

from . import core as _core
from .core import *  # noqa: F401,F403
from .core import AppConfig, DEFAULT_DATABASE_URL, load_config

__all__ = list(_core.__all__)
