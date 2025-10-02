"""Priority parsing helpers for orchestrator configuration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .jsonx import safe_loads

__all__ = ["parse_priority_map"]


def _coerce_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _parse_csv(value: str) -> dict[str, int]:
    mapping: dict[str, int] = {}
    if not value:
        return mapping
    for item in value.split(","):
        key, sep, raw = item.partition(":")
        if not sep:
            # Ignore entries without an explicit value assignment. The caller
            # will fall back to the provided defaults when no valid entries
            # remain.
            continue
        name = key.strip()
        if not name:
            continue
        mapping[name] = _coerce_int(raw.strip())
    return mapping


def parse_priority_map(env_val: str | None, default: Mapping[str, int]) -> dict[str, int]:
    """Parse orchestrator priority mappings from JSON or CSV."""

    default_map = dict(default)
    if not env_val:
        return default_map
    raw = env_val.strip()
    if not raw:
        return default_map
    try:
        parsed = safe_loads(raw)
    except Exception:  # pragma: no cover - decode handled in tests
        parsed = None
    if isinstance(parsed, Mapping):
        mapping: dict[str, int] = {}
        for key, value in parsed.items():
            name = str(key).strip()
            if not name:
                continue
            mapping[name] = _coerce_int(value)
        if mapping:
            return mapping
    csv_mapping = _parse_csv(raw)
    if csv_mapping:
        return csv_mapping
    return default_map
