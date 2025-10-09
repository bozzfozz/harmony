"""Add queue job payload_json and stop_reason columns."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Shared guards for idempotent operations.
from app.migrations import helpers

# revision identifiers, used by Alembic.
revision = "202406141200"
down_revision = "8f43f3f38e0b"
branch_labels = None
depends_on = None


_TABLE_NAME = "queue_jobs"


def upgrade() -> None:
    connection = op.get_bind()
    inspector = helpers.get_inspector(connection)

    if not helpers.has_table(inspector, _TABLE_NAME):
        return

    columns = helpers.column_map(inspector, _TABLE_NAME)

    payload_column = columns.get("payload_json")
    if payload_column is None:
        op.add_column(
            _TABLE_NAME,
            sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        )
        columns = helpers.column_map(inspector, _TABLE_NAME)
        payload_column = columns.get("payload_json")
        if "payload" in columns:
            op.execute(
                sa.text(
                    "UPDATE queue_jobs SET payload_json = payload " "WHERE payload_json IS NULL"
                )
            )

    if payload_column is not None and payload_column.get("nullable", True):
        with op.batch_alter_table(_TABLE_NAME) as batch_op:
            batch_op.alter_column(
                "payload_json",
                existing_type=postgresql.JSONB(),
                nullable=False,
            )

    if "stop_reason" not in columns:
        op.add_column(
            _TABLE_NAME,
            sa.Column("stop_reason", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    op.drop_column(_TABLE_NAME, "stop_reason")
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.drop_column("payload_json")
