"""Add artist release pruning columns and audit table."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "202411011200"
down_revision = "202410211200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    release_columns = {column["name"] for column in inspector.get_columns("artist_releases")}
    if "inactive_at" not in release_columns:
        op.add_column("artist_releases", sa.Column("inactive_at", sa.DateTime(), nullable=True))
    if "inactive_reason" not in release_columns:
        op.add_column("artist_releases", sa.Column("inactive_reason", sa.Text(), nullable=True))

    existing_indexes = {index["name"] for index in inspector.get_indexes("artist_releases")}
    if "ix_artist_releases_inactive_at" not in existing_indexes:
        op.create_index(
            "ix_artist_releases_inactive_at",
            "artist_releases",
            ["inactive_at"],
            unique=False,
        )

    if "artist_audit" not in inspector.get_table_names():
        op.create_table(
            "artist_audit",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("job_id", sa.String(length=64), nullable=True),
            sa.Column("artist_key", sa.String(length=255), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("entity_id", sa.String(length=255), nullable=True),
            sa.Column("event", sa.String(length=32), nullable=False),
            sa.Column("before", sa.JSON(), nullable=True),
            sa.Column("after", sa.JSON(), nullable=True),
        )
        op.create_index("ix_artist_audit_artist_key", "artist_audit", ["artist_key"], unique=False)
        op.create_index("ix_artist_audit_event", "artist_audit", ["event"], unique=False)
        op.create_index("ix_artist_audit_created_at", "artist_audit", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "artist_audit" in inspector.get_table_names():
        op.drop_index("ix_artist_audit_created_at", table_name="artist_audit")
        op.drop_index("ix_artist_audit_event", table_name="artist_audit")
        op.drop_index("ix_artist_audit_artist_key", table_name="artist_audit")
        op.drop_table("artist_audit")

    existing_indexes = {index["name"] for index in inspector.get_indexes("artist_releases")}
    if "ix_artist_releases_inactive_at" in existing_indexes:
        op.drop_index("ix_artist_releases_inactive_at", table_name="artist_releases")

    release_columns = {column["name"] for column in inspector.get_columns("artist_releases")}
    if "inactive_reason" in release_columns:
        op.drop_column("artist_releases", "inactive_reason")
    if "inactive_at" in release_columns:
        op.drop_column("artist_releases", "inactive_at")
