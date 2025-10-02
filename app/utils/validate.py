"""Validation helpers."""

from __future__ import annotations

__all__ = ["clamp_int", "require_non_empty", "positive_int"]


def clamp_int(value: int, minimum: int, maximum: int) -> int:
    """Clamp ``value`` to the inclusive ``[minimum, maximum]`` range."""

    if minimum > maximum:
        raise ValueError("minimum must not exceed maximum")
    return max(minimum, min(int(value), maximum))


def require_non_empty(name: str, value: str) -> str:
    """Ensure that ``value`` is not blank."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def positive_int(value: int) -> int:
    """Return ``value`` if it is positive, otherwise raise ``ValueError``."""

    number = int(value)
    if number <= 0:
        raise ValueError("value must be positive")
    return number
