"""Use JSONB for remaining columns and enforce UTC defaults."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202412181230_jsonb_utc_defaults"
down_revision = "202412011200_align_postgres_types"
branch_labels = None
depends_on = None

UTC_NOW = sa.text("timezone('utc', now())")


def upgrade() -> None:
    op.alter_column(
        "downloads",
        "request_payload",
        existing_type=postgresql.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="request_payload::jsonb",
    )

    op.alter_column(
        "artist_records",
        "genres",
        existing_type=postgresql.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=False,
        server_default=sa.text("'[]'::jsonb"),
        postgresql_using="genres::jsonb",
    )
    op.alter_column(
        "artist_records",
        "images",
        existing_type=postgresql.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=False,
        server_default=sa.text("'[]'::jsonb"),
        postgresql_using="images::jsonb",
    )
    op.alter_column(
        "artist_records",
        "metadata",
        existing_type=postgresql.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=False,
        server_default=sa.text("'{}'::jsonb"),
        postgresql_using="metadata::jsonb",
    )

    op.alter_column(
        "artist_releases",
        "metadata",
        existing_type=postgresql.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=False,
        server_default=sa.text("'{}'::jsonb"),
        postgresql_using="metadata::jsonb",
    )

    op.alter_column(
        "artist_audit",
        "before",
        existing_type=postgresql.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="before::jsonb",
    )
    op.alter_column(
        "artist_audit",
        "after",
        existing_type=postgresql.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="after::jsonb",
    )

    op.alter_column(
        "worker_jobs",
        "payload",
        existing_type=postgresql.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=False,
        postgresql_using="payload::jsonb",
    )

    op.alter_column(
        "queue_jobs",
        "available_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=UTC_NOW,
        existing_server_default=sa.text("now()"),
    )
    op.alter_column(
        "queue_jobs",
        "created_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=UTC_NOW,
        existing_server_default=sa.text("now()"),
    )
    op.alter_column(
        "queue_jobs",
        "updated_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=UTC_NOW,
        existing_server_default=sa.text("now()"),
    )

    op.alter_column(
        "activity_events",
        "timestamp",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=UTC_NOW,
        existing_server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.alter_column(
        "activity_events",
        "timestamp",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
        existing_server_default=UTC_NOW,
    )

    op.alter_column(
        "queue_jobs",
        "updated_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
        existing_server_default=UTC_NOW,
    )
    op.alter_column(
        "queue_jobs",
        "created_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
        existing_server_default=UTC_NOW,
    )
    op.alter_column(
        "queue_jobs",
        "available_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
        existing_server_default=UTC_NOW,
    )

    op.alter_column(
        "worker_jobs",
        "payload",
        existing_type=postgresql.JSONB(),
        type_=postgresql.JSON(),
        existing_nullable=False,
        postgresql_using="payload::json",
    )

    op.alter_column(
        "artist_audit",
        "after",
        existing_type=postgresql.JSONB(),
        type_=postgresql.JSON(),
        existing_nullable=True,
        postgresql_using="after::json",
    )
    op.alter_column(
        "artist_audit",
        "before",
        existing_type=postgresql.JSONB(),
        type_=postgresql.JSON(),
        existing_nullable=True,
        postgresql_using="before::json",
    )

    op.alter_column(
        "artist_releases",
        "metadata",
        existing_type=postgresql.JSONB(),
        type_=postgresql.JSON(),
        existing_nullable=False,
        server_default=sa.text("'{}'::json"),
        postgresql_using="metadata::json",
    )

    op.alter_column(
        "artist_records",
        "metadata",
        existing_type=postgresql.JSONB(),
        type_=postgresql.JSON(),
        existing_nullable=False,
        server_default=sa.text("'{}'::json"),
        postgresql_using="metadata::json",
    )
    op.alter_column(
        "artist_records",
        "images",
        existing_type=postgresql.JSONB(),
        type_=postgresql.JSON(),
        existing_nullable=False,
        server_default=sa.text("'[]'::json"),
        postgresql_using="images::json",
    )
    op.alter_column(
        "artist_records",
        "genres",
        existing_type=postgresql.JSONB(),
        type_=postgresql.JSON(),
        existing_nullable=False,
        server_default=sa.text("'[]'::json"),
        postgresql_using="genres::json",
    )

    op.alter_column(
        "downloads",
        "request_payload",
        existing_type=postgresql.JSONB(),
        type_=postgresql.JSON(),
        existing_nullable=True,
        postgresql_using="request_payload::json",
    )
