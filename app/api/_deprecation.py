"""Compat re-export for legacy API deprecation helpers."""

from __future__ import annotations

from app._legacy import warn_legacy_import

__all__ = ["warn_legacy_import"]
