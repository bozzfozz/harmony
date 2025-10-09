"""Shared helpers for database migration tests."""

from __future__ import annotations

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.dialects import postgresql

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

_JSONB_COLUMNS: tuple[tuple[str, str], ...] = (
    ("downloads", "request_payload"),
    ("activity_events", "details"),
    ("artist_records", "genres"),
    ("artist_records", "images"),
    ("artist_records", "metadata"),
    ("artist_releases", "metadata"),
    ("artist_audit", "before"),
    ("artist_audit", "after"),
    ("worker_jobs", "payload"),
    ("queue_jobs", "payload"),
    ("queue_jobs", "payload_json"),
    ("queue_jobs", "result_payload"),
)

_TIMESTAMPTZ_COLUMNS: tuple[tuple[str, str], ...] = (
    ("queue_jobs", "available_at"),
    ("queue_jobs", "lease_expires_at"),
    ("queue_jobs", "created_at"),
    ("queue_jobs", "updated_at"),
    ("activity_events", "timestamp"),
)


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
    queue_columns = inspector.get_columns("queue_jobs")
    columns = {column["name"] for column in queue_columns}
    missing_columns: set[str] = _REQUIRED_QUEUE_COLUMNS - columns
    assert not missing_columns, f"Missing columns: {sorted(missing_columns)}"

    indexes = {index["name"] for index in inspector.get_indexes("queue_jobs")}
    missing_indexes: set[str] = _REQUIRED_QUEUE_INDEXES - indexes
    assert not missing_indexes, f"Missing indexes: {sorted(missing_indexes)}"

    payload_column = _get_column(queue_columns, "payload_json")
    assert isinstance(
        payload_column["type"], postgresql.JSONB
    ), "queue_jobs.payload_json should be JSONB"
    result_column = _get_column(queue_columns, "result_payload")
    assert isinstance(
        result_column["type"], postgresql.JSONB
    ), "queue_jobs.result_payload should be JSONB"

    for column_name in ("available_at", "lease_expires_at", "created_at", "updated_at"):
        column = _get_column(queue_columns, column_name)
        column_type = column["type"]
        assert isinstance(
            column_type, postgresql.TIMESTAMP
        ), f"queue_jobs.{column_name} should use TIMESTAMPTZ"
        assert (
            getattr(column_type, "timezone", False) is True
        ), f"queue_jobs.{column_name} must be timezone aware"


def assert_postgresql_types(engine: sa.Engine) -> None:
    """Validate that reflected column types use PostgreSQL-native variants."""

    inspector = sa.inspect(engine)

    for table, column in _JSONB_COLUMNS:
        info = _get_column(inspector.get_columns(table), column)
        assert isinstance(
            info["type"], postgresql.JSONB
        ), f"{table}.{column} should be JSONB"

    for table, column in _TIMESTAMPTZ_COLUMNS:
        info = _get_column(inspector.get_columns(table), column)
        column_type = info["type"]
        assert isinstance(
            column_type, postgresql.TIMESTAMP
        ), f"{table}.{column} should use TIMESTAMPTZ"
        assert getattr(column_type, "timezone", False) is True, (
            f"{table}.{column} must be timezone aware"
        )


def _get_column(columns: list[dict[str, object]], name: str) -> dict[str, object]:
    for column in columns:
        if column.get("name") == name:
            return column
    available = ", ".join(sorted(str(column.get("name")) for column in columns))
    raise AssertionError(f"Column {name!r} not found; available columns: {available}")
