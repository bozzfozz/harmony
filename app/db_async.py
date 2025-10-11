"""Async database helpers for Harmony."""

from __future__ import annotations

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import load_config

_async_engine: AsyncEngine | None = None
AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None
_configured_async_url: str | None = None


def _ensure_async_engine() -> None:
    global _async_engine, AsyncSessionLocal, _configured_async_url

    config = load_config()
    async_url = config.database.url
    url = make_url(async_url)
    driver = url.drivername.lower()
    if not driver.startswith("sqlite+aiosqlite"):
        raise ValueError(f"Unsupported database driver for async engine: {driver}")

    if _async_engine is not None and _configured_async_url == async_url:
        return

    _async_engine = create_async_engine(async_url, future=True)
    AsyncSessionLocal = async_sessionmaker(
        _async_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    _configured_async_url = async_url


def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if AsyncSessionLocal is None:
        _ensure_async_engine()
    if AsyncSessionLocal is None:
        raise RuntimeError("Async session factory is not initialized.")
    return AsyncSessionLocal


def get_async_session() -> AsyncSession:
    factory = get_async_sessionmaker()
    return factory()


async def reset_async_engine_for_tests() -> None:
    global _async_engine, AsyncSessionLocal, _configured_async_url

    engine = _async_engine
    _async_engine = None
    AsyncSessionLocal = None
    _configured_async_url = None
    if engine is not None:
        await engine.dispose()


__all__ = [
    "AsyncSessionLocal",
    "get_async_session",
    "get_async_sessionmaker",
    "reset_async_engine_for_tests",
]
