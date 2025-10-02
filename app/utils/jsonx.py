"""Safe JSON serialisation helpers."""

from __future__ import annotations

import json
from typing import Any

__all__ = ["safe_dumps", "safe_loads", "try_parse_json_or_none"]


def _default(value: Any) -> str:
    return str(value)


def safe_dumps(obj: Any) -> str:
    """Serialise ``obj`` to JSON using deterministic formatting."""

    return json.dumps(
        obj,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=_default,
    )


def safe_loads(data: str | bytes | bytearray) -> Any:
    """Parse JSON data strictly, rejecting blank inputs."""

    if isinstance(data, (bytes, bytearray)):
        text = data.decode("utf-8")
    elif isinstance(data, str):
        text = data
    else:
        raise TypeError("data must be str or bytes")
    stripped = text.strip()
    if not stripped:
        raise ValueError("data must not be empty")
    return json.loads(stripped)


def try_parse_json_or_none(data: str | bytes | bytearray | None) -> Any | None:
    """Return parsed JSON or ``None`` for invalid/blank input."""

    if data is None:
        return None
    try:
        return safe_loads(data)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
