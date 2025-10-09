"""Database configuration and helper utilities."""

from __future__ import annotations

import asyncio
from contextlib import AbstractContextManager, contextmanager
import logging
from pathlib import Path
from typing import Callable, Iterator, Optional, TypeVar

try:  # pragma: no cover - optional dependency support for local tooling
    from alembic import command
    from alembic.config import Config
except ImportError:  # pragma: no cover - allow fallback during tests/offline use
    command = None  # type: ignore[assignment]
    Config = None  # type: ignore[assignment]
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import load_config


class Base(DeclarativeBase):
    pass


# Expose metadata so Alembic can import a single canonical reference.
metadata = Base.metadata


_engine: Optional[Engine] = None
SessionLocal: Optional[sessionmaker[Session]] = None
_initializing_db: bool = False

_logger = logging.getLogger(__name__)
_ALEMBIC_INI_PATH = Path(__file__).resolve().parents[1] / "alembic.ini"
_ALEMBIC_SCRIPT_LOCATION = Path(__file__).resolve().parent / "migrations"

T = TypeVar("T")

SessionCallable = Callable[[Session], T]
SessionFactory = Callable[[], AbstractContextManager[Session]]


def _build_engine(database_url: str) -> Engine:
    return create_engine(database_url)


def _ensure_engine(*, auto_init: bool = True) -> None:
    global _engine, SessionLocal, _initializing_db

    config = load_config()
    database_url = config.database.url
    if _engine is not None and str(_engine.url) == database_url:
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
        _ensure_engine(auto_init=False)
        if _engine is None:
            raise RuntimeError("Database engine was not initialised before migrations.")
        if command is None or Config is None:
            _logger.warning("Alembic is not available; falling back to Base.metadata.create_all().")
            from app import models  # noqa: F401  # Import models for metadata side-effects

            Base.metadata.create_all(bind=_engine, checkfirst=True)
        else:
            config = _configure_alembic(str(_engine.url))
            command.upgrade(config, "head")
    finally:
        _initializing_db = False


def reset_engine_for_tests() -> None:
    """Reset the cached engine/session so tests get a clean database handle."""

    global _engine, SessionLocal, _initializing_db

    if _engine is not None:
        _engine.dispose()

    _engine = None
    SessionLocal = None
    _initializing_db = False


def _configure_alembic(database_url: str) -> Config:
    if Config is None:
        raise RuntimeError("Alembic configuration is unavailable; ensure alembic is installed.")
    config = Config(str(_ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(_ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logger"] = False
    return config


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
