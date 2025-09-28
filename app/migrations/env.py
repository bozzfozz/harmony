"""Alembic environment configuration for Harmony."""

from __future__ import annotations

from logging.config import fileConfig
from typing import Optional

from alembic import context
from alembic.config import Config
from sqlalchemy import engine_from_config, pool

from app.config import load_config
from app.db import Base

# Import models for metadata registration
from app import models  # noqa: F401

_context_config = getattr(context, "config", None)
config = _context_config if _context_config is not None else Config()

if getattr(config, "config_file_name", None):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_database_url(alembic_config: Optional[Config]) -> str:
    if alembic_config is not None:
        candidate = alembic_config.get_main_option("sqlalchemy.url")
        if candidate:
            return candidate
    return load_config().database.url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    url = _resolve_database_url(config)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=_resolve_database_url(config),
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


def get_database_url(alembic_config: Optional[Config] = None) -> str:
    """Expose URL resolution for unit tests."""

    return _resolve_database_url(alembic_config or config)


if _context_config is not None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
