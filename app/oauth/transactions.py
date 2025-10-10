"""Core models and error types for OAuth transaction storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, MutableMapping, Protocol

__all__ = [
    "OAuthTransaction",
    "Transaction",
    "TransactionExpiredError",
    "TransactionNotFoundError",
    "TransactionStoreError",
    "TransactionUsedError",
]


@dataclass(slots=True, frozen=True)
class Transaction:
    """Immutable representation of a stored OAuth transaction."""

    state: str
    code_verifier: str
    meta: Mapping[str, Any]
    issued_at: datetime
    expires_at: datetime

    def is_expired(self, *, reference: datetime | None = None) -> bool:
        moment = reference or datetime.now(timezone.utc)
        return moment >= self.expires_at


# Backwards compatibility alias retained for historical imports.
OAuthTransaction = Transaction


class TransactionStoreError(RuntimeError):
    """Base error for OAuth transaction store failures."""


class TransactionNotFoundError(TransactionStoreError):
    """Raised when a transaction does not exist."""


class TransactionUsedError(TransactionStoreError):
    """Raised when a transaction has already been consumed."""


class TransactionExpiredError(TransactionStoreError):
    """Raised when a transaction exists but is past its TTL."""


class OAuthTransactionStore(Protocol):
    """Protocol describing the behaviour of an OAuth transaction store."""

    @property
    def ttl(self) -> timedelta:
        ...

    def create(
        self,
        state: str,
        code_verifier: str,
        meta: Mapping[str, Any] | MutableMapping[str, Any],
        ttl_seconds: int,
    ) -> None:
        ...

    def consume(self, state: str) -> Transaction:
        ...

    def exists(self, state: str) -> bool:
        ...

    def purge_expired(self, *, reference: datetime | None = None) -> int:
        ...

    def count(self) -> int:
        ...
