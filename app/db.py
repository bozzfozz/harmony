"""Database configuration and helper utilities."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
import logging
from pathlib import Path
from typing import TypeVar

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_env, load_config


class Base(DeclarativeBase):
    pass


metadata = Base.metadata


_engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None
_initializing_db = False

_logger = logging.getLogger(__name__)

T = TypeVar("T")

SessionCallable = Callable[[Session], T]
SessionFactory = Callable[[], AbstractContextManager[Session]]


def _synchronous_url(url: URL) -> URL:
    driver = url.drivername.lower()
    if driver in {"sqlite", "sqlite+aiosqlite"}:
        return url.set(drivername="sqlite+pysqlite")
    return url


def _database_file_path(url: URL) -> Path | None:
    database = url.database
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _should_reset_database() -> bool:
    value = get_env("DB_RESET")
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _build_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    sync_url = _synchronous_url(url)
    connect_args: dict[str, object] = {}
    if sync_url.drivername.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(sync_url, future=True, connect_args=connect_args)


def _dispose_engine() -> None:
    global _engine, SessionLocal

    if _engine is not None:
        _engine.dispose()

    _engine = None
    SessionLocal = None


def _prepare_database_file(url: URL, *, reset: bool) -> tuple[Path | None, bool]:
    path = _database_file_path(url)
    if path is None:
        return None, False

    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()

    if reset and existed:
        try:
            path.unlink()
        except OSError as exc:  # pragma: no cover - defensive guard
            _logger.warning("Failed to remove database file during reset", exc_info=exc)
        existed = False

    return path, not existed


def _ensure_engine(*, auto_init: bool = True) -> None:
    global _engine, SessionLocal, _initializing_db

    config = load_config()
    database_url = config.database.url
    target_url = _synchronous_url(make_url(database_url)).render_as_string(hide_password=False)

    if _engine is not None and str(_engine.url) == target_url:
        return

    _dispose_engine()

    _engine = _build_engine(database_url)
    SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    if auto_init and not _initializing_db:
        init_db()


def get_session() -> Session:
    if SessionLocal is None:
        _ensure_engine()
    if SessionLocal is None:
        raise RuntimeError("Database session factory is not initialized.")
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
        config = load_config()
        database_url = config.database.url
        url = make_url(database_url)
        reset_requested = _should_reset_database()

        if reset_requested:
            _logger.info("DB_RESET requested; refreshing database file")
            _dispose_engine()

        _, created = _prepare_database_file(url, reset=reset_requested)

        _ensure_engine(auto_init=False)
        if _engine is None:
            raise RuntimeError("Database engine was not initialised before bootstrap.")

        from app import models  # noqa: F401

        Base.metadata.create_all(bind=_engine, checkfirst=True)

        if created:
            _logger.info("Database bootstrap completed", extra={"event": "database.bootstrap"})
    finally:
        _initializing_db = False


def reset_engine_for_tests() -> None:
    """Reset the cached engine/session so tests get a clean database handle."""

    global _initializing_db

    _dispose_engine()
    _initializing_db = False


__all__ = [
    "Base",
    "metadata",
    "SessionLocal",
    "get_session",
    "session_scope",
    "run_session",
    "init_db",
    "reset_engine_for_tests",
    "_engine",
]


def _call_with_session(func: SessionCallable[T], *, factory: SessionFactory | None = None) -> T:
    context = factory() if factory is not None else session_scope()
    with context as session:
        return func(session)


async def run_session(func: SessionCallable[T], *, factory: SessionFactory | None = None) -> T:
    """Execute ``func`` with a database session in a worker thread."""

    return await asyncio.to_thread(_call_with_session, func, factory=factory)
