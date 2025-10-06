"""Shared helpers for database migration tests."""

from __future__ import annotations

import sqlalchemy as sa
from alembic.config import Config

_REQUIRED_QUEUE_COLUMNS = {
    "id",
    "type",
    "status",
    "payload_json",
    "priority",
    "attempts",
    "available_at",
    "lease_expires_at",
    "idempotency_key",
    "last_error",
    "stop_reason",
    "updated_at",
}

_REQUIRED_QUEUE_INDEXES = {
    "ix_queue_jobs_type_status_available_at",
    "ix_queue_jobs_lease_expires_at",
    "ix_queue_jobs_idempotency_key_not_null",
}


def make_config(database_url: str) -> Config:
    """Return an Alembic config bound to the given database URL."""

    config = Config("alembic.ini")
    config.set_main_option("script_location", "app/migrations")
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logger"] = False
    return config


def assert_queue_jobs_schema(engine: sa.Engine) -> None:
    """Ensure the queue_jobs table contains the expected schema objects."""

    inspector = sa.inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("queue_jobs")}
    missing_columns: set[str] = _REQUIRED_QUEUE_COLUMNS - columns
    assert not missing_columns, f"Missing columns: {sorted(missing_columns)}"

    indexes = {index["name"] for index in inspector.get_indexes("queue_jobs")}
    missing_indexes: set[str] = _REQUIRED_QUEUE_INDEXES - indexes
    assert not missing_indexes, f"Missing indexes: {sorted(missing_indexes)}"
