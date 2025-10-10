from datetime import datetime, timedelta, timezone

import pytest

from app.services.oauth_transactions import (
    OAuthTransaction,
    OAuthTransactionStore,
    TransactionNotFoundError,
)


@pytest.fixture
def store() -> OAuthTransactionStore:
    reference = datetime(2024, 1, 1, tzinfo=timezone.utc)
    now = reference

    def _now() -> datetime:
        nonlocal now
        return now

    instance = OAuthTransactionStore(ttl=timedelta(minutes=5), now_fn=_now)

    def _advance(seconds: float) -> None:
        nonlocal now
        now = reference + timedelta(seconds=seconds)

    instance._advance = _advance  # type: ignore[attr-defined]
    return instance


def _transaction(state: str, created: datetime | None = None) -> OAuthTransaction:
    created_at = created or datetime(2024, 1, 1, tzinfo=timezone.utc)
    return OAuthTransaction(
        provider="spotify",
        state=state,
        code_verifier="verifier",
        code_challenge="challenge",
        code_challenge_method="S256",
        redirect_uri="http://127.0.0.1:8888/callback",
        created_at=created_at,
        client_hint_ip="192.0.2.1",
    )


def test_save_and_consume(store: OAuthTransactionStore) -> None:
    txn = _transaction("state-1")
    store.save(txn)

    fetched = store.get("state-1")
    assert fetched is not None
    assert fetched.state == "state-1"

    consumed = store.consume("state-1")
    assert consumed.state == "state-1"

    with pytest.raises(TransactionNotFoundError):
        store.consume("state-1")


def test_consume_expired_transaction(store: OAuthTransactionStore) -> None:
    txn = _transaction("expired")
    store.save(txn)
    store._advance(3600)  # type: ignore[attr-defined]

    with pytest.raises(TransactionNotFoundError):
        store.consume("expired")


def test_count_purges_expired(store: OAuthTransactionStore) -> None:
    recent = _transaction("recent")
    old = _transaction("old", created=datetime(2023, 12, 31, 23, 0, tzinfo=timezone.utc))
    store.save(recent)
    store.save(old)

    assert store.count() == 1

