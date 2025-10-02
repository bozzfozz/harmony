"""Compatibility shim for legacy request logging imports."""

from __future__ import annotations

from app.logging_events import log_event

__all__ = ["log_event"]
