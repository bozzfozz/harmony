from __future__ import annotations

import warnings

from app.hdm.idempotency import (
    IdempotencyReservation,
    IdempotencyStore,
    InMemoryIdempotencyStore,
)

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.idempotency instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "IdempotencyReservation",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
]
