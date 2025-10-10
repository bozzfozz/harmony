from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.oauth.store_fs import FsOAuthTransactionStore
from app.oauth.transactions import (
    TransactionExpiredError,
    TransactionNotFoundError,
    TransactionUsedError,
)


@pytest.fixture()
def fs_store(tmp_path: Path) -> FsOAuthTransactionStore:
    current = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    def now() -> datetime:
        return current

    store = FsOAuthTransactionStore(
        tmp_path,
        ttl=timedelta(seconds=60),
        hash_code_verifier=False,
        now_fn=now,
    )

    def advance(seconds: int) -> None:
        nonlocal current
        current = current + timedelta(seconds=seconds)

    store._advance = advance  # type: ignore[attr-defined]
    return store


def test_create_and_consume(fs_store: FsOAuthTransactionStore) -> None:
    fs_store.create(
        state="state-1",
        code_verifier="verifier",
        meta={"provider": "spotify"},
        ttl_seconds=30,
    )
    txn = fs_store.consume("state-1")
    assert txn.code_verifier == "verifier"
    assert txn.meta["provider"] == "spotify"

    with pytest.raises(TransactionUsedError):
        fs_store.consume("state-1")


def test_missing_state(fs_store: FsOAuthTransactionStore) -> None:
    with pytest.raises(TransactionNotFoundError):
        fs_store.consume("missing")


def test_expired_state(fs_store: FsOAuthTransactionStore) -> None:
    fs_store.create(
        state="state-expire",
        code_verifier="verifier",
        meta={},
        ttl_seconds=10,
    )
    fs_store._advance(20)  # type: ignore[attr-defined]
    with pytest.raises(TransactionExpiredError):
        fs_store.consume("state-expire")


def test_purge_expired(fs_store: FsOAuthTransactionStore) -> None:
    fs_store.create(
        state="stay",
        code_verifier="stay",  # nosec: B106 - test data only
        meta={},
        ttl_seconds=60,
    )
    fs_store.create(
        state="expire",
        code_verifier="expire",  # nosec: B106 - test data only
        meta={},
        ttl_seconds=10,
    )
    fs_store._advance(30)  # type: ignore[attr-defined]
    removed = fs_store.purge_expired()
    assert removed == 1
    assert fs_store.exists("stay") is True
    with pytest.raises(TransactionExpiredError):
        fs_store.consume("expire")
