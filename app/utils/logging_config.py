"""Compatibility wrapper exposing logging helpers for legacy imports."""

from __future__ import annotations

from app.logging import configure_logging, get_logger

__all__ = ["configure_logging", "get_logger"]
