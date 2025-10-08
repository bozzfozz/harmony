"""Shared utilities for emitting deprecation warnings for legacy modules."""

from __future__ import annotations

from warnings import warn


def warn_legacy_import(old: str, new: str) -> None:
    """Emit a deprecation warning for a legacy import path."""

    warn(
        f"{old} is deprecated; use {new}",
        DeprecationWarning,
        stacklevel=2,
    )


__all__ = ["warn_legacy_import"]
