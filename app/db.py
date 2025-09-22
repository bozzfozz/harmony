"""Database configuration and helper utilities."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import load_config


class Base(DeclarativeBase):
    pass


_config = load_config()
_engine = create_engine(
    _config.database.url,
    connect_args={"check_same_thread": False}
    if _config.database.url.startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session() -> Session:
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
    from app import models  # Import models for metadata

    Base.metadata.create_all(bind=_engine)


__all__ = ["Base", "SessionLocal", "get_session", "session_scope", "init_db", "_engine"]
