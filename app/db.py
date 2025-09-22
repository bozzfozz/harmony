"""Database configuration and helper utilities."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import load_config


class Base(DeclarativeBase):
    pass


_engine: Optional[Engine] = None
SessionLocal: Optional[sessionmaker[Session]] = None
_configured_database_url: Optional[str] = None
_initializing_db: bool = False


def _build_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def _resolve_sqlite_path(database_url: str) -> Optional[Path]:
    try:
        url = make_url(database_url)
    except Exception:  # pragma: no cover - defensive parsing
        return None

    if url.get_backend_name() != "sqlite":
        return None

    database = url.database or ""
    if database in {":memory:", ""}:
        return None

    return Path(database)


def _ensure_engine(*, auto_init: bool = True) -> None:
    global _engine, SessionLocal, _configured_database_url, _initializing_db

    config = load_config()
    database_url = config.database.url
    sqlite_path = _resolve_sqlite_path(database_url)

    reuse_existing = False
    if _engine is not None and database_url == _configured_database_url:
        if sqlite_path is None or sqlite_path.exists() or not auto_init:
            reuse_existing = True

    if reuse_existing:
        return

    if _engine is not None:
        _engine.dispose()

    _engine = _build_engine(database_url)
    SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    _configured_database_url = database_url

    if (
        auto_init
        and not _initializing_db
        and sqlite_path is not None
        and not sqlite_path.exists()
    ):
        init_db()


def get_session() -> Session:
    if SessionLocal is None:
        _ensure_engine()
    assert SessionLocal is not None  # For type checkers
    return SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    global _initializing_db

    if _initializing_db:
        return

    _initializing_db = True
    try:
        _ensure_engine(auto_init=False)
        assert _engine is not None
        from app import models  # Import models for metadata

        Base.metadata.create_all(bind=_engine)
    finally:
        _initializing_db = False


def reset_engine_for_tests() -> None:
    """Reset the cached engine/session so tests get a clean database handle."""

    global _engine, SessionLocal, _configured_database_url, _initializing_db

    if _engine is not None:
        _engine.dispose()

    _engine = None
    SessionLocal = None
    _configured_database_url = None
    _initializing_db = False


__all__ = [
    "Base",
    "SessionLocal",
    "get_session",
    "session_scope",
    "init_db",
    "reset_engine_for_tests",
    "_engine",
]
