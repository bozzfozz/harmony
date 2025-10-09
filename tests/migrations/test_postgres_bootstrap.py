"""Smoke tests for Alembic bootstrap behaviour on PostgreSQL."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.migrations.helpers import (assert_activity_events_schema,
                                      assert_queue_jobs_schema, make_config)
from tests.support.postgres import postgres_schema

pytestmark = pytest.mark.postgres


def _create_legacy_queue_jobs(engine: sa.Engine) -> None:
    ddl = sa.text(
        """
        CREATE TABLE queue_jobs (
            id SERIAL PRIMARY KEY,
            type VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            priority INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            lease_expires_at TIMESTAMPTZ,
            idempotency_key VARCHAR(128),
            last_error TEXT,
            result_payload JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    with engine.begin() as connection:
        connection.execute(ddl)
        connection.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_queue_jobs_type_status_available_at "
                "ON queue_jobs (type, status, available_at)"
            )
        )


def test_upgrade_head_idempotent_on_fresh_schema() -> None:
    with postgres_schema("bootstrap") as schema:
        config = make_config(schema.sync_url())
        command.upgrade(config, "head")

        engine = sa.create_engine(schema.sync_url())
        try:
            assert_queue_jobs_schema(engine)
            assert_activity_events_schema(engine)
        finally:
            engine.dispose()

        # A second upgrade must be a no-op on an already stamped database.
        command.upgrade(config, "head")


def test_upgrade_adopts_existing_queue_jobs_table() -> None:
    with postgres_schema("bootstrap_existing") as schema:
        engine = sa.create_engine(schema.sync_url())
        try:
            _create_legacy_queue_jobs(engine)
        finally:
            engine.dispose()

        config = make_config(schema.sync_url())
        command.upgrade(config, "head")

        engine = sa.create_engine(schema.sync_url())
        try:
            assert_queue_jobs_schema(engine)
        finally:
            engine.dispose()
