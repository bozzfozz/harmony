"""Regression tests for the queue job idempotency index migration."""

from __future__ import annotations

from datetime import datetime

from alembic import command
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tests.support.postgres import postgres_schema

from .helpers import make_config

pytestmark = pytest.mark.postgres


def _insert_job(
    connection: sa.Connection,
    table: sa.Table,
    *,
    job_type: str,
    idempotency_key: str | None,
    status: str = "pending",
) -> None:
    connection.execute(
        table.insert(),
        {
            "type": job_type,
            "status": status,
            "payload_json": {},
            "priority": 0,
            "attempts": 0,
            "available_at": datetime.utcnow(),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "idempotency_key": idempotency_key,
        },
    )


def test_queue_job_idempotency_index_survives_reset_cycle() -> None:
    with postgres_schema("queue_idempotency") as schema:
        config = make_config(schema.sync_url())

        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "head")

        engine = sa.create_engine(schema.sync_url())
        try:
            inspector = sa.inspect(engine)
            indexes = {index["name"] for index in inspector.get_indexes("queue_jobs")}
            assert "ix_queue_jobs_idempotency_key_not_null" in indexes
        finally:
            engine.dispose()


def test_queue_job_idempotency_enforces_uniqueness() -> None:
    with postgres_schema("queue_idempotency_unique") as schema:
        config = make_config(schema.sync_url())

        command.upgrade(config, "head")

        engine = sa.create_engine(schema.sync_url())
        try:
            metadata = sa.MetaData()
            queue_jobs = sa.Table("queue_jobs", metadata, autoload_with=engine)

            with engine.begin() as connection:
                _insert_job(connection, queue_jobs, job_type="sync", idempotency_key="dupe")

                with pytest.raises(IntegrityError):
                    _insert_job(
                        connection,
                        queue_jobs,
                        job_type="sync",
                        idempotency_key="dupe",
                    )

                _insert_job(connection, queue_jobs, job_type="sync", idempotency_key=None)
                _insert_job(connection, queue_jobs, job_type="sync", idempotency_key=None)

                with pytest.raises(IntegrityError):
                    _insert_job(
                        connection,
                        queue_jobs,
                        job_type="other",
                        idempotency_key="dupe",
                    )

            inspector = sa.inspect(engine)
            indexes = {index["name"]: index for index in inspector.get_indexes("queue_jobs")}
            assert indexes["ix_queue_jobs_idempotency_key_not_null"]["unique"]

            with engine.connect() as connection:
                definition = connection.execute(
                    sa.text(
                        """
                        SELECT indexdef
                        FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND tablename = 'queue_jobs'
                          AND indexname = 'ix_queue_jobs_idempotency_key_not_null'
                        """
                    )
                ).scalar_one()
            assert "WHERE idempotency_key IS NOT NULL" in definition
        finally:
            engine.dispose()
