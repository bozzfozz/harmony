"""Utility helpers for Harmony."""

from __future__ import annotations

from .logging_config import configure_logging, get_logger

__all__ = ["configure_logging", "get_logger", "activity_manager", "record_activity"]


def __getattr__(name: str):
    if name in {"activity_manager", "record_activity"}:
        from .activity import activity_manager, record_activity

        mapping = {
            "activity_manager": activity_manager,
            "record_activity": record_activity,
        }
        return mapping[name]
    raise AttributeError(name)
