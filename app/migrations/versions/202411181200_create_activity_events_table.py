"""Create activity_events table for storing activity audit records."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.migrations import helpers

revision = "202411181200"
down_revision = "202411151200"
branch_labels = None
depends_on = None


_TABLE = "activity_events"
_INDEX = "ix_activity_events_type_status_timestamp"


def upgrade() -> None:
    inspector = helpers.get_inspector()
    if not helpers.has_table(inspector, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
            sa.Column(
                "timestamp",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("timezone('utc', now())"),
            ),
            sa.Column("type", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=128), nullable=False),
            sa.Column("details", postgresql.JSONB(), nullable=True),
        )
    helpers.create_index_if_missing(
        inspector, _TABLE, _INDEX, ["type", "status", "timestamp"]
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
