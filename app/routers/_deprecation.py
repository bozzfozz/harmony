"""Shared helpers for legacy router shims."""

from __future__ import annotations

from warnings import warn

LEGACY_ROUTER_REMOVAL_DATE = "2025-06-30"


def emit_router_deprecation(module_name: str, replacement: str, *, stacklevel: int = 2) -> None:
    warn(
        (
            f"{module_name} is deprecated and will be removed on {LEGACY_ROUTER_REMOVAL_DATE}; "
            f"use {replacement} instead."
        ),
        DeprecationWarning,
        stacklevel=stacklevel,
    )


__all__ = ["LEGACY_ROUTER_REMOVAL_DATE", "emit_router_deprecation"]
