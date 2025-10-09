"""Migration smoke tests against PostgreSQL when available."""

from __future__ import annotations

from alembic import command
import pytest
import sqlalchemy as sa

from tests.support.postgres import postgres_schema

from .helpers import (
    assert_activity_events_schema,
    assert_postgresql_types,
    assert_queue_jobs_schema,
    make_config,
)

pytestmark = pytest.mark.postgres


def test_upgrade_downgrade_postgres() -> None:
    with postgres_schema("migrations") as schema:
        config = make_config(schema.sync_url())

        command.upgrade(config, "head")
        engine = sa.create_engine(schema.sync_url())
        try:
            assert_queue_jobs_schema(engine)
            assert_activity_events_schema(engine)
            assert_postgresql_types(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "base")
        command.upgrade(config, "head")

        engine = sa.create_engine(schema.sync_url())
        try:
            assert_queue_jobs_schema(engine)
            assert_activity_events_schema(engine)
            assert_postgresql_types(engine)
        finally:
            engine.dispose()
