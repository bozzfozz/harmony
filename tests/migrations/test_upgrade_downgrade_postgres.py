"""Migration smoke tests against PostgreSQL when available."""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.schema import CreateSchema, DropSchema

from .helpers import assert_queue_jobs_schema, make_config


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL is not configured for PostgreSQL tests",
)
def test_upgrade_downgrade_postgres() -> None:
    database_url = os.environ["DATABASE_URL"]
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        pytest.skip("PostgreSQL URL required for migration smoke test")

    schema_name = f"test_migrations_{uuid.uuid4().hex}"
    base_engine = sa.create_engine(url)
    try:
        with base_engine.connect() as connection:
            connection.execute(CreateSchema(schema_name))
            connection.commit()

        scoped_url = url.set(query={**url.query, "options": f"-csearch_path={schema_name}"})
        config = make_config(str(scoped_url))

        command.upgrade(config, "head")
        engine = sa.create_engine(scoped_url)
        try:
            assert_queue_jobs_schema(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "base")
        command.upgrade(config, "head")

        engine = sa.create_engine(scoped_url)
        try:
            assert_queue_jobs_schema(engine)
        finally:
            engine.dispose()
    finally:
        with base_engine.connect() as connection:
            try:
                connection.execute(DropSchema(schema_name, cascade=True))
                connection.commit()
            except ProgrammingError:
                connection.rollback()
        base_engine.dispose()
