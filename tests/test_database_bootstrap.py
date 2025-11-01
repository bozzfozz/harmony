"""Regression tests for the database bootstrap helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys
from typing import Any, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy.engine import URL
from sqlalchemy.exc import MissingGreenlet

import app.db as db


class _Disposable(Protocol):
    url: URL

    def dispose(self) -> None:
        """Dispose of the engine resources."""


def test_ensure_engine_uses_synchronous_sqlite_url(monkeypatch, tmp_path) -> None:
    """Ensure ``_ensure_engine`` upgrades sqlite URLs to the sync driver."""

    db.reset_engine_for_tests()

    captured_url: URL | None = None

    class DummyEngine:
        def __init__(self, url: URL) -> None:
            self.url = url

        def dispose(self) -> None:  # pragma: no cover - defensive guard
            pass

    def fake_create_engine(url: URL, *args: Any, **kwargs: Any) -> _Disposable:
        nonlocal captured_url
        captured_url = url
        return DummyEngine(url)

    def fake_sessionmaker(**kwargs: Any) -> Callable[[], None]:
        return lambda: None

    monkeypatch.setattr(db, "load_config", lambda: None)
    monkeypatch.setattr(db, "init_db", lambda: None)
    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    monkeypatch.setattr(db, "sessionmaker", fake_sessionmaker)

    raw_url = f"sqlite:///{tmp_path / 'harmony-test.db'}"
    monkeypatch.setattr(db, "get_database_url", lambda: raw_url)

    try:
        db._ensure_engine()
        assert captured_url is not None
        assert captured_url.drivername == "sqlite+pysqlite"
    finally:
        db.reset_engine_for_tests()


def test_init_db_does_not_raise_missing_greenlet(monkeypatch, tmp_path) -> None:
    """``init_db`` should bootstrap synchronously without ``MissingGreenlet``."""

    db.reset_engine_for_tests()

    database_path = tmp_path / "bootstrap.db"
    raw_url = f"sqlite:///{database_path}"

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test-database-bootstrap")
    monkeypatch.setattr(db, "load_config", lambda: None)
    monkeypatch.setattr(db, "apply_schema_migrations", lambda engine: None)
    monkeypatch.setattr(db, "get_database_url", lambda: raw_url)

    import app.config.database as db_config

    monkeypatch.setattr(db_config, "HARMONY_DATABASE_FILE", database_path, raising=False)
    monkeypatch.setattr(db_config, "HARMONY_DATABASE_URL", raw_url, raising=False)
    monkeypatch.setattr(db_config, "get_database_url", lambda: raw_url, raising=False)

    try:
        try:
            db.init_db()
        except MissingGreenlet as exc:  # pragma: no cover - failure guard
            pytest.fail(f"init_db raised MissingGreenlet: {exc}")
    finally:
        db.reset_engine_for_tests()
