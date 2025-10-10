from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.oauth.store_memory import MemoryOAuthTransactionStore
from app.oauth.transactions import (
    TransactionExpiredError,
    TransactionNotFoundError,
    TransactionUsedError,
)


@pytest.fixture()
def memory_store() -> MemoryOAuthTransactionStore:
    current = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    def now() -> datetime:
        return current

    store = MemoryOAuthTransactionStore(ttl=timedelta(seconds=60), now_fn=now)

    def advance(seconds: int) -> None:
        nonlocal current
        current = current + timedelta(seconds=seconds)

    store._advance = advance  # type: ignore[attr-defined]
    return store


def test_create_and_consume(memory_store: MemoryOAuthTransactionStore) -> None:
    memory_store.create(
        state="state-1",
        code_verifier="verifier",
        meta={"provider": "spotify"},
        ttl_seconds=30,
    )
    txn = memory_store.consume("state-1")
    assert txn.code_verifier == "verifier"
    assert txn.meta["provider"] == "spotify"

    with pytest.raises(TransactionUsedError):
        memory_store.consume("state-1")


def test_consume_missing(memory_store: MemoryOAuthTransactionStore) -> None:
    with pytest.raises(TransactionNotFoundError):
        memory_store.consume("unknown")


def test_expired_transaction(memory_store: MemoryOAuthTransactionStore) -> None:
    memory_store.create(
        state="state-expired",
        code_verifier="verifier",
        meta={},
        ttl_seconds=10,
    )
    memory_store._advance(20)  # type: ignore[attr-defined]
    with pytest.raises(TransactionExpiredError):
        memory_store.consume("state-expired")


def test_purge_expired(memory_store: MemoryOAuthTransactionStore) -> None:
    memory_store.create(
        state="stay",
        code_verifier="verifier",
        meta={},
        ttl_seconds=60,
    )
    memory_store.create(
        state="expire",
        code_verifier="verifier",
        meta={},
        ttl_seconds=10,
    )
    memory_store._advance(30)  # type: ignore[attr-defined]
    removed = memory_store.purge_expired()
    assert removed == 1
    assert memory_store.exists("stay") is True
    with pytest.raises(TransactionExpiredError):
        memory_store.consume("expire")
