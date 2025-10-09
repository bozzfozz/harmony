"""Helpers for provisioning isolated PostgreSQL schemas in tests."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import NoSuchModuleError, OperationalError, ProgrammingError
from sqlalchemy.schema import CreateSchema, DropSchema


@dataclass
class ScopedPostgresSchema:
    """Metadata about a temporary PostgreSQL schema."""

    url: URL
    schema_name: str

    def sync_url(self) -> str:
        """Return a SQLAlchemy URL string for synchronous engines."""

        return self.url.render_as_string(hide_password=False)

    def async_url(self) -> str:
        """Return an asyncpg-compatible SQLAlchemy URL string."""

        async_url = self.url.set(drivername="postgresql+asyncpg")
        return async_url.render_as_string(hide_password=False)


@contextmanager
def postgres_schema(prefix: str, *, monkeypatch: pytest.MonkeyPatch | None = None):
    """Yield a temporary PostgreSQL schema for the duration of a test.

    The helper skips the caller when no ``DATABASE_URL`` is configured or when the
    URL does not point to PostgreSQL. If the database is unreachable an
    explanatory skip is raised instead of failing the suite.
    """

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is not configured for PostgreSQL tests")

    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        pytest.skip("PostgreSQL URL required for this test")

    schema_name = f"{prefix}_{uuid.uuid4().hex}"
    try:
        engine = sa.create_engine(url)
    except (
        NoSuchModuleError,
        ImportError,
    ) as exc:  # pragma: no cover - environment guard
        pytest.skip(f"PostgreSQL driver unavailable: {exc}")

    created_schema = False
    try:
        try:
            with engine.connect() as connection:
                connection.execute(CreateSchema(schema_name))
                connection.commit()
            created_schema = True
        except OperationalError as exc:  # pragma: no cover - environment guard
            engine.dispose()
            pytest.skip(
                "PostgreSQL is unavailable: start a local instance (for example "
                "with `docker compose up -d postgres`) or update DATABASE_URL to "
                f"reference an accessible server. (Original error: {exc})"
            )

        scoped_url = url.set(
            query={**url.query, "options": f"-csearch_path={schema_name}"}
        )
        rendered = scoped_url.render_as_string(hide_password=False)
        if monkeypatch is not None:
            monkeypatch.setenv("DATABASE_URL", rendered)

        yield ScopedPostgresSchema(url=scoped_url, schema_name=schema_name)
    finally:
        if created_schema:
            with engine.connect() as connection:
                try:
                    connection.execute(DropSchema(schema_name, cascade=True))
                    connection.commit()
                except ProgrammingError:
                    connection.rollback()
        engine.dispose()


__all__ = ["ScopedPostgresSchema", "postgres_schema"]
