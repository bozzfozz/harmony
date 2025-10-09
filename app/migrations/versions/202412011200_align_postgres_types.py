"""Align queue job JSON columns and timestamps with PostgreSQL-native types."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "202412011200_align_postgres_types"
down_revision = "202411181200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "queue_jobs",
        "payload",
        existing_type=postgresql.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=False,
        postgresql_using="payload::jsonb",
    )
    op.alter_column(
        "queue_jobs",
        "result_payload",
        existing_type=postgresql.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="result_payload::jsonb",
    )
    op.alter_column(
        "queue_jobs",
        "payload_json",
        existing_type=postgresql.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=False,
        postgresql_using="payload_json::jsonb",
    )

    op.alter_column(
        "queue_jobs",
        "available_at",
        existing_type=sa.DateTime(timezone=False),
        type_=postgresql.TIMESTAMP(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="available_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "queue_jobs",
        "lease_expires_at",
        existing_type=sa.DateTime(timezone=False),
        type_=postgresql.TIMESTAMP(timezone=True),
        existing_nullable=True,
        postgresql_using="lease_expires_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "queue_jobs",
        "created_at",
        existing_type=sa.DateTime(timezone=False),
        type_=postgresql.TIMESTAMP(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "queue_jobs",
        "updated_at",
        existing_type=sa.DateTime(timezone=False),
        type_=postgresql.TIMESTAMP(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )

    op.alter_column(
        "activity_events",
        "timestamp",
        existing_type=sa.DateTime(timezone=False),
        type_=postgresql.TIMESTAMP(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="timestamp AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    op.alter_column(
        "activity_events",
        "timestamp",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        type_=sa.DateTime(timezone=False),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="timestamp AT TIME ZONE 'UTC'",
    )

    op.alter_column(
        "queue_jobs",
        "updated_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        type_=sa.DateTime(timezone=False),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "queue_jobs",
        "created_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        type_=sa.DateTime(timezone=False),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "queue_jobs",
        "lease_expires_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        type_=sa.DateTime(timezone=False),
        existing_nullable=True,
        postgresql_using="lease_expires_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "queue_jobs",
        "available_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        type_=sa.DateTime(timezone=False),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="available_at AT TIME ZONE 'UTC'",
    )

    op.alter_column(
        "queue_jobs",
        "payload_json",
        existing_type=postgresql.JSONB(),
        type_=postgresql.JSON(),
        existing_nullable=False,
        postgresql_using="payload_json::json",
    )
    op.alter_column(
        "queue_jobs",
        "result_payload",
        existing_type=postgresql.JSONB(),
        type_=postgresql.JSON(),
        existing_nullable=True,
        postgresql_using="result_payload::json",
    )
    op.alter_column(
        "queue_jobs",
        "payload",
        existing_type=postgresql.JSONB(),
        type_=postgresql.JSON(),
        existing_nullable=False,
        postgresql_using="payload::json",
    )
