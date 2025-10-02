"""Add queue job payload_json and stop_reason columns with guards."""

from __future__ import annotations

from typing import Iterable

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import NoSuchTableError

# revision identifiers, used by Alembic.
revision = "202406141200"
down_revision = "8f43f3f38e0b"
branch_labels = None
depends_on = None


_TABLE_NAME = "queue_jobs"


def _get_column_names(connection: Connection) -> set[str]:
    try:
        inspector = sa.inspect(connection)
        return {column["name"] for column in inspector.get_columns(_TABLE_NAME)}
    except NoSuchTableError:
        return set()


def _get_index_names(connection: Connection) -> set[str]:
    try:
        inspector = sa.inspect(connection)
        return {index["name"] for index in inspector.get_indexes(_TABLE_NAME)}
    except NoSuchTableError:
        return set()


def _has_table(connection: Connection) -> bool:
    return connection.dialect.has_table(connection, _TABLE_NAME)


def upgrade() -> None:
    connection = op.get_bind()
    if not _has_table(connection):
        return

    json_type = sa.JSON().with_variant(sa.Text(), "sqlite")

    column_names = _get_column_names(connection)

    if "payload_json" not in column_names:
        op.add_column(
            _TABLE_NAME,
            sa.Column("payload_json", json_type, nullable=True),
        )
        column_names.add("payload_json")

        if "payload" in column_names:
            op.execute(
                text("UPDATE queue_jobs SET payload_json = payload " "WHERE payload_json IS NULL")
            )

        with op.batch_alter_table(_TABLE_NAME) as batch_op:
            batch_op.alter_column(
                "payload_json",
                existing_type=json_type,
                nullable=False,
            )

    if "stop_reason" not in column_names:
        op.add_column(
            _TABLE_NAME,
            sa.Column("stop_reason", sa.String(length=64), nullable=True),
        )

    existing_indexes = _get_index_names(connection)
    desired_indexes: dict[str, Iterable[str]] = {
        "ix_queue_jobs_type_status_available_at": ("type", "status", "available_at"),
        "ix_queue_jobs_lease_expires_at": ("lease_expires_at",),
        "ix_queue_jobs_idempotency_key": ("idempotency_key",),
    }

    for index_name, columns in desired_indexes.items():
        if index_name not in existing_indexes:
            op.create_index(index_name, _TABLE_NAME, list(columns))


def downgrade() -> None:
    connection = op.get_bind()
    if not _has_table(connection):
        return

    column_names = _get_column_names(connection)

    if "stop_reason" in column_names:
        op.drop_column(_TABLE_NAME, "stop_reason")

    if "payload_json" in column_names:
        with op.batch_alter_table(_TABLE_NAME) as batch_op:
            batch_op.drop_column("payload_json")

    # Indexes existed in the previous revision already; downgrade intentionally
    # leaves them untouched to avoid destructive churn.
