"""Extend watchlist_artists with async scheduling columns."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "202411151200"
down_revision = "202411011200"
branch_labels = None
depends_on = None


_TABLE = "watchlist_artists"


def _column_names(connection) -> set[str]:
    inspector = inspect(connection)
    return {column["name"] for column in inspector.get_columns(_TABLE)}


def _index_names(connection) -> set[str]:
    inspector = inspect(connection)
    return {index["name"] for index in inspector.get_indexes(_TABLE)}


def upgrade() -> None:
    connection = op.get_bind()
    columns = _column_names(connection)

    if "source_artist_id" not in columns:
        op.add_column(_TABLE, sa.Column("source_artist_id", sa.Integer(), nullable=True))
    if "priority" not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "priority",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if "cooldown_s" not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "cooldown_s",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if "last_scan_at" not in columns:
        op.add_column(_TABLE, sa.Column("last_scan_at", sa.DateTime(), nullable=True))
    if "last_hash" not in columns:
        op.add_column(_TABLE, sa.Column("last_hash", sa.String(length=128), nullable=True))
    if "retry_budget_left" not in columns:
        op.add_column(_TABLE, sa.Column("retry_budget_left", sa.Integer(), nullable=True))
    if "stop_reason" not in columns:
        op.add_column(_TABLE, sa.Column("stop_reason", sa.String(length=128), nullable=True))
    if "updated_at" not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    indexes = _index_names(connection)
    if "ix_watchlist_artists_source_artist_id" not in indexes:
        op.create_index(
            "ix_watchlist_artists_source_artist_id",
            _TABLE,
            ["source_artist_id"],
            unique=True,
        )
    if "ix_watchlist_artists_priority_last_scan" not in indexes:
        op.create_index(
            "ix_watchlist_artists_priority_last_scan",
            _TABLE,
            ["priority", "last_scan_at", "id"],
        )
    if "ix_watchlist_artists_stop_reason" not in indexes:
        op.create_index("ix_watchlist_artists_stop_reason", _TABLE, ["stop_reason"])
    if "ix_watchlist_artists_retry_budget_left" not in indexes:
        op.create_index(
            "ix_watchlist_artists_retry_budget_left",
            _TABLE,
            ["retry_budget_left"],
        )


def downgrade() -> None:
    connection = op.get_bind()
    indexes = _index_names(connection)

    if "ix_watchlist_artists_retry_budget_left" in indexes:
        op.drop_index(
            "ix_watchlist_artists_retry_budget_left",
            table_name=_TABLE,
        )
    if "ix_watchlist_artists_stop_reason" in indexes:
        op.drop_index("ix_watchlist_artists_stop_reason", table_name=_TABLE)
    if "ix_watchlist_artists_priority_last_scan" in indexes:
        op.drop_index(
            "ix_watchlist_artists_priority_last_scan",
            table_name=_TABLE,
        )
    if "ix_watchlist_artists_source_artist_id" in indexes:
        op.drop_index(
            "ix_watchlist_artists_source_artist_id",
            table_name=_TABLE,
        )

    columns = _column_names(connection)
    for column in (
        "updated_at",
        "stop_reason",
        "retry_budget_left",
        "last_hash",
        "last_scan_at",
        "cooldown_s",
        "priority",
        "source_artist_id",
    ):
        if column in columns:
            op.drop_column(_TABLE, column)
