"""Create queue jobs table with PostgreSQL-native types."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Local helpers keep the migration idempotent when tables already exist.
from app.migrations import helpers

# revision identifiers, used by Alembic.
revision = "8f43f3f38e0b"
down_revision = "b4e3a1f6c8f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = helpers.get_inspector(connection)

    if not helpers.has_table(inspector, "queue_jobs"):
        op.create_table(
            "queue_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("type", sa.String(length=64), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.Column(
                "priority",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "attempts",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "available_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "lease_expires_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=True,
            ),
            sa.Column("idempotency_key", sa.String(length=128), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("result_payload", postgresql.JSONB(), nullable=True),
            sa.Column(
                "created_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "priority >= 0",
                name="ck_queue_jobs_priority_non_negative",
            ),
            sa.CheckConstraint(
                "attempts >= 0",
                name="ck_queue_jobs_attempts_non_negative",
            ),
            sa.CheckConstraint(
                "status IN ('pending','leased','completed','failed','cancelled')",
                name="ck_queue_jobs_status_valid",
            ),
        )

    helpers.create_index_if_missing(
        inspector,
        "queue_jobs",
        "ix_queue_jobs_type_status_available_at",
        ["type", "status", "available_at"],
    )
    helpers.create_index_if_missing(
        inspector,
        "queue_jobs",
        "ix_queue_jobs_lease_expires_at",
        ["lease_expires_at"],
    )
    helpers.create_index_if_missing(
        inspector,
        "queue_jobs",
        "ix_queue_jobs_idempotency_key",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_table("queue_jobs")
