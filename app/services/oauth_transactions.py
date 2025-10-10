"""Stateful storage for short-lived OAuth transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Callable, Dict, Optional

__all__ = ["OAuthTransaction", "OAuthTransactionStore", "TransactionNotFoundError"]


@dataclass(slots=True)
class OAuthTransaction:
    """In-memory representation of a pending OAuth callback exchange."""

    provider: str
    state: str
    code_verifier: str
    code_challenge: str
    code_challenge_method: str
    redirect_uri: str
    created_at: datetime
    client_hint_ip: str | None = None

    def is_expired(self, *, ttl: timedelta, reference: datetime | None = None) -> bool:
        """Return ``True`` if the transaction is past its allowed lifetime."""

        now = reference or datetime.now(timezone.utc)
        return self.created_at + ttl <= now


class TransactionNotFoundError(KeyError):
    """Raised when attempting to consume an unknown OAuth transaction."""


class OAuthTransactionStore:
    """Thread-safe storage for OAuth transactions with TTL enforcement."""

    def __init__(
        self,
        *,
        ttl: timedelta,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("OAuth transaction TTL must be positive")
        self._ttl = ttl
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self._transactions: Dict[str, OAuthTransaction] = {}
        self._lock = Lock()

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def _purge_expired(self, *, reference: datetime) -> None:
        expired_states = [
            state
            for state, txn in self._transactions.items()
            if txn.is_expired(ttl=self._ttl, reference=reference)
        ]
        for state in expired_states:
            self._transactions.pop(state, None)

    def save(self, transaction: OAuthTransaction) -> None:
        """Persist a new transaction, replacing any existing state."""

        if not transaction.state:
            raise ValueError("Transaction state must be non-empty")
        reference = self._now()
        with self._lock:
            self._purge_expired(reference=reference)
            self._transactions[transaction.state] = transaction

    def get(self, state: str) -> Optional[OAuthTransaction]:
        """Return the transaction for ``state`` without consuming it."""

        reference = self._now()
        with self._lock:
            self._purge_expired(reference=reference)
            return self._transactions.get(state)

    def consume(self, state: str) -> OAuthTransaction:
        """Remove and return the transaction associated with ``state``."""

        reference = self._now()
        with self._lock:
            self._purge_expired(reference=reference)
            try:
                transaction = self._transactions.pop(state)
            except KeyError as exc:  # pragma: no cover - defensive
                raise TransactionNotFoundError(state) from exc
        if transaction.is_expired(ttl=self._ttl, reference=reference):
            raise TransactionNotFoundError(state)
        return transaction

    def count(self) -> int:
        """Return the number of currently active transactions."""

        reference = self._now()
        with self._lock:
            self._purge_expired(reference=reference)
            return len(self._transactions)

