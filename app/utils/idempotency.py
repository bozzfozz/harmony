"""Idempotency helpers providing stable hash keys."""

from __future__ import annotations

import hashlib

__all__ = ["make_idempotency_key"]

_Part = str | bytes


def _normalise_part(part: _Part) -> bytes:
    if isinstance(part, bytes):
        return part
    if isinstance(part, str):
        return part.encode("utf-8")
    msg = "idempotency key parts must be str or bytes"
    raise TypeError(msg)


def make_idempotency_key(*parts: _Part) -> str:
    """Return a stable 32 character SHA256 based idempotency key."""

    if not parts:
        raise ValueError("at least one part must be provided")
    digest = hashlib.sha256()
    for part in parts:
        data = _normalise_part(part)
        digest.update(len(data).to_bytes(4, "big"))
        digest.update(data)
    return digest.hexdigest()[:32]
