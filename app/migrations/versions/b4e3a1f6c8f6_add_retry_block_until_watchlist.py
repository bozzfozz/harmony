"""Add persistent retry_block_until timestamp for watchlist artists."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b4e3a1f6c8f6"
down_revision = "7c9bdb5e1a3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {column["name"] for column in inspector.get_columns("watchlist_artists")}
    if "retry_block_until" not in columns:
        op.add_column(
            "watchlist_artists",
            sa.Column("retry_block_until", sa.DateTime(), nullable=True),
        )

    indexes = {index["name"] for index in inspector.get_indexes("watchlist_artists")}
    if "ix_watchlist_retry_block_until" not in indexes:
        op.create_index(
            "ix_watchlist_retry_block_until",
            "watchlist_artists",
            ["retry_block_until"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    indexes = {index["name"] for index in inspector.get_indexes("watchlist_artists")}
    if "ix_watchlist_retry_block_until" in indexes:
        op.drop_index("ix_watchlist_retry_block_until", table_name="watchlist_artists")

    columns = {column["name"] for column in inspector.get_columns("watchlist_artists")}
    if "retry_block_until" in columns:
        op.drop_column("watchlist_artists", "retry_block_until")
