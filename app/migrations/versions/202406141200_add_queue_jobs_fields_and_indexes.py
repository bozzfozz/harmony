"""Add queue job payload_json and stop_reason columns."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "202406141200"
down_revision = "8f43f3f38e0b"
branch_labels = None
depends_on = None


_TABLE_NAME = "queue_jobs"


def upgrade() -> None:
    op.add_column(
        _TABLE_NAME,
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE queue_jobs SET payload_json = payload WHERE payload_json IS NULL"
        )
    )
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.alter_column(
            "payload_json",
            existing_type=postgresql.JSONB(),
            nullable=False,
        )

    op.add_column(
        _TABLE_NAME,
        sa.Column("stop_reason", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(_TABLE_NAME, "stop_reason")
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.drop_column("payload_json")
