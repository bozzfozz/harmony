"""In-memory OAuth transaction store for single-process deployments."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from .transactions import (
    OAuthTransactionStore,
    Transaction,
    TransactionExpiredError,
    TransactionNotFoundError,
    TransactionStoreError,
    TransactionUsedError,
)

__all__ = ["MemoryOAuthTransactionStore"]


class MemoryOAuthTransactionStore(OAuthTransactionStore):
    """Thread-safe in-memory implementation of :class:`OAuthTransactionStore`."""

    def __init__(
        self,
        *,
        ttl: timedelta,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("OAuth transaction TTL must be positive")
        self._ttl = ttl
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._pending: dict[str, Transaction] = {}
        self._consumed: set[str] = set()
        self._lock = Lock()

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def _make_transaction(
        self,
        *,
        state: str,
        code_verifier: str,
        meta: Mapping[str, Any],
        ttl_seconds: int,
    ) -> Transaction:
        issued_at = self._now()
        expires_at = issued_at + timedelta(seconds=ttl_seconds)
        return Transaction(
            state=state,
            code_verifier=code_verifier,
            meta=dict(meta),
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def create(
        self,
        state: str,
        code_verifier: str,
        meta: Mapping[str, Any],
        ttl_seconds: int,
    ) -> None:
        if not state:
            raise TransactionStoreError("state must be provided")
        transaction = self._make_transaction(
            state=state,
            code_verifier=code_verifier,
            meta=meta,
            ttl_seconds=ttl_seconds,
        )
        with self._lock:
            if state in self._consumed:
                raise TransactionUsedError(state)
            self._purge_expired(reference=transaction.issued_at)
            self._pending[state] = transaction

    def consume(self, state: str) -> Transaction:
        reference = self._now()
        with self._lock:
            self._purge_expired(reference=reference)
            try:
                transaction = self._pending.pop(state)
            except KeyError:
                if state in self._consumed:
                    raise TransactionUsedError(state)
                raise TransactionNotFoundError(state)
            if transaction.is_expired(reference=reference):
                self._consumed.add(state)
                raise TransactionExpiredError(state)
            self._consumed.add(state)
            return transaction

    def exists(self, state: str) -> bool:
        with self._lock:
            return state in self._pending or state in self._consumed

    def purge_expired(self, *, reference: datetime | None = None) -> int:
        moment = reference or self._now()
        with self._lock:
            return self._purge_expired(reference=moment)

    def _purge_expired(self, *, reference: datetime) -> int:
        expired = [key for key, txn in self._pending.items() if txn.is_expired(reference=reference)]
        for key in expired:
            self._pending.pop(key, None)
            self._consumed.add(key)
        return len(expired)

    def count(self) -> int:
        with self._lock:
            reference = self._now()
            self._purge_expired(reference=reference)
            return len(self._pending)
