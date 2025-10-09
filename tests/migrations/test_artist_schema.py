"""Regression tests for artist-related migrations on PostgreSQL."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from tests.support.postgres import postgres_schema

from .helpers import make_config

pytestmark = pytest.mark.postgres


def test_migration_adds_inactive_columns_and_audit_table() -> None:
    with postgres_schema("artist_schema") as schema:
        config = make_config(schema.sync_url())
        command.upgrade(config, "head")

        engine = sa.create_engine(schema.sync_url())
        try:
            inspector = sa.inspect(engine)

            release_columns = {
                column["name"]: column
                for column in inspector.get_columns("artist_releases")
            }
            assert {"inactive_at", "inactive_reason"} <= release_columns.keys()
            assert isinstance(release_columns["inactive_at"]["type"], sa.DateTime)
            assert isinstance(release_columns["inactive_reason"]["type"], sa.Text)

            release_indexes = {
                index["name"] for index in inspector.get_indexes("artist_releases")
            }
            assert "ix_artist_releases_inactive_at" in release_indexes

            audit_columns = {
                column["name"]: column
                for column in inspector.get_columns("artist_audit")
            }
            expected = {
                "created_at",
                "job_id",
                "artist_key",
                "entity_type",
                "entity_id",
                "event",
            }
            assert expected <= audit_columns.keys()
            assert isinstance(audit_columns["created_at"]["type"], sa.DateTime)
            job_id_type = audit_columns["job_id"]["type"]
            assert isinstance(job_id_type, sa.String)
            assert job_id_type.length == 64

            audit_indexes = {
                index["name"] for index in inspector.get_indexes("artist_audit")
            }
            assert {
                "ix_artist_audit_artist_key",
                "ix_artist_audit_event",
                "ix_artist_audit_created_at",
            } <= audit_indexes
        finally:
            engine.dispose()
