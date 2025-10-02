"""Domain-specific errors for Harmony core modules."""

from __future__ import annotations


class InvalidInputError(ValueError):
    """Raised when invalid data is supplied to core domain operations."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


__all__ = ["InvalidInputError"]
