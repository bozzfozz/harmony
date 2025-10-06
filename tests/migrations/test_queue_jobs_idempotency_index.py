"""Regression tests for the queue job idempotency index migration."""

from __future__ import annotations

from datetime import datetime
from importlib import import_module
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError

from .helpers import make_config

_MIGRATION = import_module("app.migrations.versions.202409201200_queue_job_idempotency_key_unique")


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


def test_queue_job_idempotency_migration_is_reentrant(tmp_path: Path) -> None:
    database_path = tmp_path / "sqlite.db"
    database_url = f"sqlite:///{database_path}"
    config = make_config(database_url)

    command.upgrade(config, _MIGRATION.down_revision)
    command.upgrade(config, _MIGRATION.revision)
    command.downgrade(config, _MIGRATION.down_revision)
    command.upgrade(config, _MIGRATION.revision)

    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        indexes = {index["name"] for index in inspector.get_indexes("queue_jobs")}
        assert "ix_queue_jobs_idempotency_key_not_null" in indexes
    finally:
        engine.dispose()


def test_queue_job_idempotency_enforces_uniqueness(tmp_path: Path) -> None:
    database_path = tmp_path / "sqlite.db"
    database_url = f"sqlite:///{database_path}"
    config = make_config(database_url)

    command.upgrade(config, "head")

    engine = sa.create_engine(database_url)
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
    finally:
        engine.dispose()
