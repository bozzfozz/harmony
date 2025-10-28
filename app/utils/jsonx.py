"""Safe JSON serialisation helpers."""

from __future__ import annotations

from collections.abc import Set as AbstractSet
import json
from typing import Any

_BUFFER_TYPES = (bytes, bytearray, memoryview)

__all__ = ["safe_dumps", "safe_loads", "try_parse_json_or_none"]


def _sort_key_for_set(value: Any) -> tuple[str, str]:
    """Return a deterministic sort key for set members."""

    type_name = type(value).__qualname__
    try:
        # Serialise using the same rules as ``safe_dumps`` to ensure nested
        # structures (e.g. sets within sets) are handled consistently.
        serialised = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=_default,
        )
    except TypeError:
        serialised = repr(value)
    return type_name, serialised


def _normalise_set(value: AbstractSet[Any]) -> list[Any]:
    try:
        return sorted(value)
    except TypeError:
        return sorted(value, key=_sort_key_for_set)


def _default(value: Any) -> Any:
    if isinstance(value, AbstractSet):
        return _normalise_set(value)
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


def safe_loads(data: str | bytes | bytearray | memoryview) -> Any:
    """Parse JSON data strictly, rejecting blank inputs."""

    if isinstance(data, _BUFFER_TYPES):
        buffer: bytes
        if isinstance(data, bytes):
            buffer = data
        else:
            buffer = bytes(data)
        if not buffer.strip():
            raise ValueError("data must not be empty")
        return json.loads(buffer)
    if isinstance(data, str):
        stripped = data.strip()
        if not stripped:
            raise ValueError("data must not be empty")
        return json.loads(stripped)
    raise TypeError("data must be str or bytes")


def try_parse_json_or_none(
    data: str | bytes | bytearray | memoryview | None,
) -> Any | None:
    """Return parsed JSON or ``None`` for invalid/blank input."""

    if data is None:
        return None
    try:
        return safe_loads(data)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
