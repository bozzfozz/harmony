"""Structured logging helpers for Harmony services."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

_JSON_PRIMITIVES = (str, int, float, bool, type(None))


def _validate_flat_value(name: str, value: Any) -> None:
    if isinstance(value, _JSON_PRIMITIVES):
        return
    raise TypeError(f"Field '{name}' must be a flat JSON-compatible value")


def _ensure_meta(meta: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if meta is None:
        return None
    if not isinstance(meta, Mapping):
        raise TypeError("meta must be a mapping if provided")
    meta_dict = dict(meta)
    _validate_json_payload(meta_dict, path="meta")
    return meta_dict


def _validate_json_payload(value: Any, *, path: str) -> None:
    if isinstance(value, _JSON_PRIMITIVES):
        return
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError(f"Keys in '{path}' must be strings")
            _validate_json_payload(nested, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _validate_json_payload(nested, path=f"{path}[{index}]")
        return
    raise TypeError(f"Unsupported value in '{path}': {type(value).__name__}")


def log_event(logger: Any, event: str, /, **fields: Any) -> None:
    """Emit a structured log event with a canonical payload."""

    if not isinstance(event, str) or not event.strip():
        raise ValueError("event must be a non-empty string")

    meta = _ensure_meta(fields.pop("meta", None))

    extra: dict[str, Any] = {"event": event}
    for name, value in fields.items():
        _validate_flat_value(name, value)
        extra[name] = value
    if meta is not None:
        extra["meta"] = meta

    logger.info(event, extra=extra)


def now_ms() -> int:
    """Return the current UNIX timestamp in milliseconds."""

    return int(time.time() * 1000)
