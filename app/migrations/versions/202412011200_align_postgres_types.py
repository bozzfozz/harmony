"""Align queue job JSON columns and timestamps with PostgreSQL-native types."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "202412011200_align_postgres_types"
down_revision = "202411181200"
branch_labels = None
depends_on = None

_QUEUE_JOBS_TABLE = "queue_jobs"
_ACTIVITY_EVENTS_TABLE = "activity_events"


def _table_exists(connection: sa.engine.Connection, table_name: str) -> bool:
    query = sa.text("SELECT to_regclass(current_schema() || '.' || :table_name) IS NOT NULL")
    return bool(connection.execute(query, {"table_name": table_name}).scalar())


def _column_exists(connection: sa.engine.Connection, table_name: str, column: str) -> bool:
    query = sa.text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = :table_name
          AND column_name = :column_name
        LIMIT 1
        """
    )
    return (
        connection.execute(query, {"table_name": table_name, "column_name": column}).first()
        is not None
    )


def _ensure_jsonb(connection: sa.engine.Connection, table_name: str, column: str) -> None:
    if not _column_exists(connection, table_name, column):
        return
    op.execute(
        sa.text(
            f"ALTER TABLE {table_name} " f"ALTER COLUMN {column} TYPE JSONB USING {column}::jsonb"
        )
    )


def upgrade() -> None:
    connection = op.get_bind()

    if _table_exists(connection, _QUEUE_JOBS_TABLE):
        has_payload = _column_exists(connection, _QUEUE_JOBS_TABLE, "payload")
        has_payload_json = _column_exists(connection, _QUEUE_JOBS_TABLE, "payload_json")

        if has_payload and not has_payload_json:
            op.execute(sa.text("ALTER TABLE queue_jobs RENAME COLUMN payload TO payload_json"))
            has_payload = False
            has_payload_json = True

        if has_payload and has_payload_json:
            _ensure_jsonb(connection, _QUEUE_JOBS_TABLE, "payload_json")
            op.execute(
                sa.text(
                    "UPDATE queue_jobs "
                    "SET payload_json = COALESCE(payload_json, payload::jsonb) "
                    "WHERE payload_json IS NULL"
                )
            )
            op.execute(sa.text("ALTER TABLE queue_jobs DROP COLUMN payload"))
            has_payload = False
            has_payload_json = True

        if _column_exists(connection, _QUEUE_JOBS_TABLE, "payload"):
            op.execute(sa.text("ALTER TABLE queue_jobs DROP COLUMN IF EXISTS payload"))

        if _column_exists(connection, _QUEUE_JOBS_TABLE, "payload_json"):
            _ensure_jsonb(connection, _QUEUE_JOBS_TABLE, "payload_json")
            op.execute(
                sa.text(
                    "UPDATE queue_jobs "
                    "SET payload_json = '{}'::jsonb "
                    "WHERE payload_json IS NULL"
                )
            )
            op.execute(sa.text("ALTER TABLE queue_jobs ALTER COLUMN payload_json SET NOT NULL"))

        if _column_exists(connection, _QUEUE_JOBS_TABLE, "result_payload"):
            op.execute(
                sa.text(
                    "ALTER TABLE queue_jobs "
                    "ALTER COLUMN result_payload TYPE JSONB "
                    "USING result_payload::jsonb"
                )
            )

        if _column_exists(connection, _QUEUE_JOBS_TABLE, "available_at"):
            op.alter_column(
                _QUEUE_JOBS_TABLE,
                "available_at",
                existing_type=sa.DateTime(timezone=False),
                type_=postgresql.TIMESTAMP(timezone=True),
                existing_nullable=False,
                existing_server_default=sa.text("now()"),
                postgresql_using="available_at AT TIME ZONE 'UTC'",
            )
        if _column_exists(connection, _QUEUE_JOBS_TABLE, "lease_expires_at"):
            op.alter_column(
                _QUEUE_JOBS_TABLE,
                "lease_expires_at",
                existing_type=sa.DateTime(timezone=False),
                type_=postgresql.TIMESTAMP(timezone=True),
                existing_nullable=True,
                postgresql_using="lease_expires_at AT TIME ZONE 'UTC'",
            )
        if _column_exists(connection, _QUEUE_JOBS_TABLE, "created_at"):
            op.alter_column(
                _QUEUE_JOBS_TABLE,
                "created_at",
                existing_type=sa.DateTime(timezone=False),
                type_=postgresql.TIMESTAMP(timezone=True),
                existing_nullable=False,
                existing_server_default=sa.text("now()"),
                postgresql_using="created_at AT TIME ZONE 'UTC'",
            )
        if _column_exists(connection, _QUEUE_JOBS_TABLE, "updated_at"):
            op.alter_column(
                _QUEUE_JOBS_TABLE,
                "updated_at",
                existing_type=sa.DateTime(timezone=False),
                type_=postgresql.TIMESTAMP(timezone=True),
                existing_nullable=False,
                existing_server_default=sa.text("now()"),
                postgresql_using="updated_at AT TIME ZONE 'UTC'",
            )

    if _table_exists(connection, _ACTIVITY_EVENTS_TABLE):
        op.alter_column(
            _ACTIVITY_EVENTS_TABLE,
            "timestamp",
            existing_type=sa.DateTime(timezone=False),
            type_=postgresql.TIMESTAMP(timezone=True),
            existing_nullable=False,
            existing_server_default=sa.text("now()"),
            postgresql_using="timestamp AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    connection = op.get_bind()

    if _table_exists(connection, _ACTIVITY_EVENTS_TABLE):
        op.alter_column(
            _ACTIVITY_EVENTS_TABLE,
            "timestamp",
            existing_type=postgresql.TIMESTAMP(timezone=True),
            type_=sa.DateTime(timezone=False),
            existing_nullable=False,
            existing_server_default=sa.text("now()"),
            postgresql_using="timestamp AT TIME ZONE 'UTC'",
        )

    if _table_exists(connection, _QUEUE_JOBS_TABLE):
        if not _column_exists(connection, _QUEUE_JOBS_TABLE, "payload"):
            op.add_column(
                _QUEUE_JOBS_TABLE,
                sa.Column("payload", postgresql.JSON(), nullable=True),
            )
            op.execute(sa.text("UPDATE queue_jobs SET payload = payload_json::json"))
            op.execute(sa.text("ALTER TABLE queue_jobs ALTER COLUMN payload SET NOT NULL"))

        if _column_exists(connection, _QUEUE_JOBS_TABLE, "payload_json"):
            op.execute(
                sa.text(
                    "ALTER TABLE queue_jobs "
                    "ALTER COLUMN payload_json TYPE JSON "
                    "USING payload_json::json"
                )
            )

        if _column_exists(connection, _QUEUE_JOBS_TABLE, "result_payload"):
            op.execute(
                sa.text(
                    "ALTER TABLE queue_jobs "
                    "ALTER COLUMN result_payload TYPE JSON "
                    "USING result_payload::json"
                )
            )

        if _column_exists(connection, _QUEUE_JOBS_TABLE, "updated_at"):
            op.alter_column(
                _QUEUE_JOBS_TABLE,
                "updated_at",
                existing_type=postgresql.TIMESTAMP(timezone=True),
                type_=sa.DateTime(timezone=False),
                existing_nullable=False,
                existing_server_default=sa.text("now()"),
                postgresql_using="updated_at AT TIME ZONE 'UTC'",
            )
        if _column_exists(connection, _QUEUE_JOBS_TABLE, "created_at"):
            op.alter_column(
                _QUEUE_JOBS_TABLE,
                "created_at",
                existing_type=postgresql.TIMESTAMP(timezone=True),
                type_=sa.DateTime(timezone=False),
                existing_nullable=False,
                existing_server_default=sa.text("now()"),
                postgresql_using="created_at AT TIME ZONE 'UTC'",
            )
        if _column_exists(connection, _QUEUE_JOBS_TABLE, "lease_expires_at"):
            op.alter_column(
                _QUEUE_JOBS_TABLE,
                "lease_expires_at",
                existing_type=postgresql.TIMESTAMP(timezone=True),
                type_=sa.DateTime(timezone=False),
                existing_nullable=True,
                postgresql_using="lease_expires_at AT TIME ZONE 'UTC'",
            )
        if _column_exists(connection, _QUEUE_JOBS_TABLE, "available_at"):
            op.alter_column(
                _QUEUE_JOBS_TABLE,
                "available_at",
                existing_type=postgresql.TIMESTAMP(timezone=True),
                type_=sa.DateTime(timezone=False),
                existing_nullable=False,
                existing_server_default=sa.text("now()"),
                postgresql_using="available_at AT TIME ZONE 'UTC'",
            )
