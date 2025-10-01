"""Create queue jobs table with idempotent guards."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "8f43f3f38e0b"
down_revision = "b4e3a1f6c8f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = sa.JSON().with_variant(sa.Text(), "sqlite")

    if not bind.dialect.has_table(bind, "queue_jobs"):
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
            sa.Column("payload", json_type, nullable=False),
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
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column("idempotency_key", sa.String(length=128), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("result_payload", json_type, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
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

    inspector = inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("queue_jobs")}

    if "ix_queue_jobs_type_status_available_at" not in existing_indexes:
        op.create_index(
            "ix_queue_jobs_type_status_available_at",
            "queue_jobs",
            ["type", "status", "available_at"],
        )

    if "ix_queue_jobs_lease_expires_at" not in existing_indexes:
        op.create_index(
            "ix_queue_jobs_lease_expires_at",
            "queue_jobs",
            ["lease_expires_at"],
        )

    if "ix_queue_jobs_idempotency_key" not in existing_indexes:
        op.create_index(
            "ix_queue_jobs_idempotency_key",
            "queue_jobs",
            ["idempotency_key"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("queue_jobs")}

    if "ix_queue_jobs_idempotency_key" in existing_indexes:
        op.drop_index("ix_queue_jobs_idempotency_key", table_name="queue_jobs")

    if "ix_queue_jobs_lease_expires_at" in existing_indexes:
        op.drop_index("ix_queue_jobs_lease_expires_at", table_name="queue_jobs")

    if "ix_queue_jobs_type_status_available_at" in existing_indexes:
        op.drop_index(
            "ix_queue_jobs_type_status_available_at",
            table_name="queue_jobs",
        )

    if bind.dialect.has_table(bind, "queue_jobs"):
        op.drop_table("queue_jobs")
