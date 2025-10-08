"""Create activity_events table for storing activity audit records."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "202411181200"
down_revision = "202411151200"
branch_labels = None
depends_on = None


_TABLE = "activity_events"
_INDEX = "ix_activity_events_type_status_timestamp"
_JSON_TYPE = sa.JSON().with_variant(sa.Text(), "sqlite")


def _has_table(connection: Connection, table_name: str) -> bool:
    return connection.dialect.has_table(connection, table_name)


def _index_names(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    connection = op.get_bind()

    if not _has_table(connection, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "timestamp",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("type", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=128), nullable=False),
            sa.Column("details", _JSON_TYPE, nullable=True),
        )

    existing_indexes = _index_names(connection, _TABLE) if _has_table(connection, _TABLE) else set()
    if _INDEX not in existing_indexes:
        op.create_index(_INDEX, _TABLE, ["type", "status", "timestamp"])


def downgrade() -> None:
    connection = op.get_bind()

    if _has_table(connection, _TABLE):
        existing_indexes = _index_names(connection, _TABLE)
        if _INDEX in existing_indexes:
            op.drop_index(_INDEX, table_name=_TABLE)
        op.drop_table(_TABLE)
