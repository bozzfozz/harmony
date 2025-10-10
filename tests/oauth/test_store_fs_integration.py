from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.oauth.store_fs import FsOAuthTransactionStore
from app.oauth.transactions import TransactionUsedError


def _build_store(path: Path, *, current: datetime) -> tuple[FsOAuthTransactionStore, callable]:
    time_ref = current

    def now() -> datetime:
        return time_ref

    store = FsOAuthTransactionStore(
        path,
        ttl=timedelta(seconds=120),
        hash_code_verifier=False,
        now_fn=now,
    )

    def advance(seconds: int) -> None:
        nonlocal time_ref
        time_ref = time_ref + timedelta(seconds=seconds)

    return store, advance


def test_store_shared_between_instances(tmp_path: Path) -> None:
    start = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    store_a, _ = _build_store(tmp_path, current=start)
    store_b, advance_b = _build_store(tmp_path, current=start)

    store_a.create(
        state="shared",
        code_verifier="verifier",
        meta={},
        ttl_seconds=60,
    )
    advance_b(10)
    txn = store_b.consume("shared")
    assert txn.code_verifier == "verifier"

    with pytest.raises(TransactionUsedError):
        store_a.consume("shared")


def test_startup_check(tmp_path: Path) -> None:
    store, _ = _build_store(
        tmp_path,
        current=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    result = store.startup_check()
    assert result["backend"] == "fs"
    assert Path(result["base_dir"]).exists()
