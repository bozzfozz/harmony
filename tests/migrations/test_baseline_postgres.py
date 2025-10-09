"""Regression tests for the squashed baseline migration on PostgreSQL."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from tests.migrations.helpers import (
    assert_activity_events_schema,
    assert_postgresql_types,
    assert_queue_jobs_schema,
    make_config,
)
from tests.support.postgres import postgres_schema

pytestmark = pytest.mark.postgres


def _assert_tables_accessible(engine: sa.Engine, *table_names: str) -> None:
    """Execute ``SELECT`` probes to prove the tables exist."""

    with engine.connect() as connection:
        for table in table_names:
            connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 0"))


def test_upgrade_head_builds_baseline_schema() -> None:
    with postgres_schema("baseline") as schema:
        config = make_config(schema.sync_url())

        command.upgrade(config, "head")

        engine = sa.create_engine(schema.sync_url())
        try:
            assert_queue_jobs_schema(engine)
            assert_activity_events_schema(engine)
            assert_postgresql_types(engine)
            _assert_tables_accessible(
                engine,
                "queue_jobs",
                "activity_events",
                "artist_records",
                "artist_audit",
            )

            with engine.connect() as connection:
                index_rows = connection.execute(
                    sa.text(
                        """
                        SELECT indexname, indexdef
                        FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND tablename = 'queue_jobs'
                        """
                    )
                ).all()

            index_map = {row.indexname: row.indexdef for row in index_rows}
            definition = index_map.get("ix_queue_jobs_idempotency_key_not_null")
            assert definition is not None, "queue_jobs idempotency index missing"
            assert "WHERE idempotency_key IS NOT NULL" in definition
        finally:
            engine.dispose()


def test_upgrade_head_is_idempotent() -> None:
    with postgres_schema("baseline_idem") as schema:
        config = make_config(schema.sync_url())

        command.upgrade(config, "head")
        command.upgrade(config, "head")

        engine = sa.create_engine(schema.sync_url())
        try:
            assert_queue_jobs_schema(engine)
        finally:
            engine.dispose()
