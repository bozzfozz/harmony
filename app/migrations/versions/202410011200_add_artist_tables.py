"""Create persistence tables for artist metadata and watchlist entries."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

# revision identifiers, used by Alembic.
revision = "202410011200"
down_revision = "202409201200"
branch_labels = None
depends_on = None


_ARTISTS = "artists"
_ARTIST_RELEASES = "artist_releases"
_ARTIST_WATCHLIST = "artist_watchlist"


def _has_table(connection: Connection, table_name: str) -> bool:
    return connection.dialect.has_table(connection, table_name)


def _index_names(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    connection = op.get_bind()

    if not _has_table(connection, _ARTISTS):
        op.create_table(
            _ARTISTS,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("artist_key", sa.String(length=255), nullable=False),
            sa.Column("source", sa.String(length=50), nullable=False),
            sa.Column("source_id", sa.String(length=255), nullable=True),
            sa.Column("name", sa.String(length=512), nullable=False),
            sa.Column("genres", sa.JSON, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("images", sa.JSON, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("popularity", sa.Integer, nullable=True),
            sa.Column("metadata", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("etag", sa.String(length=64), nullable=False),
            sa.Column("version", sa.String(length=64), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime,
                nullable=False,
                default=datetime.utcnow,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime,
                nullable=False,
                default=datetime.utcnow,
                onupdate=datetime.utcnow,
                server_default=sa.func.now(),
            ),
        )

    existing_indexes = (
        _index_names(connection, _ARTISTS) if _has_table(connection, _ARTISTS) else set()
    )
    if "uq_artists_source_source_id" not in existing_indexes:
        op.create_index(
            "uq_artists_source_source_id",
            _ARTISTS,
            ["source", "source_id"],
            unique=True,
        )
    if "ix_artists_artist_key" not in existing_indexes:
        op.create_index(
            "ix_artists_artist_key",
            _ARTISTS,
            ["artist_key"],
            unique=True,
        )
    if "ix_artists_updated_at" not in existing_indexes:
        op.create_index("ix_artists_updated_at", _ARTISTS, ["updated_at"])

    if not _has_table(connection, _ARTIST_RELEASES):
        op.create_table(
            _ARTIST_RELEASES,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "artist_id",
                sa.Integer,
                sa.ForeignKey(f"{_ARTISTS}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("artist_key", sa.String(length=255), nullable=False),
            sa.Column("source", sa.String(length=50), nullable=False),
            sa.Column("source_id", sa.String(length=255), nullable=True),
            sa.Column("title", sa.String(length=512), nullable=False),
            sa.Column("release_date", sa.Date, nullable=True),
            sa.Column("release_type", sa.String(length=50), nullable=True),
            sa.Column("total_tracks", sa.Integer, nullable=True),
            sa.Column("version", sa.String(length=64), nullable=True),
            sa.Column("etag", sa.String(length=64), nullable=False),
            sa.Column("metadata", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
            sa.Column(
                "created_at",
                sa.DateTime,
                nullable=False,
                default=datetime.utcnow,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime,
                nullable=False,
                default=datetime.utcnow,
                onupdate=datetime.utcnow,
                server_default=sa.func.now(),
            ),
        )

    existing_indexes = (
        _index_names(connection, _ARTIST_RELEASES)
        if _has_table(connection, _ARTIST_RELEASES)
        else set()
    )
    if "uq_artist_releases_source_source_id" not in existing_indexes:
        op.create_index(
            "uq_artist_releases_source_source_id",
            _ARTIST_RELEASES,
            ["source", "source_id"],
            unique=True,
        )
    if "ix_artist_releases_artist_id" not in existing_indexes:
        op.create_index("ix_artist_releases_artist_id", _ARTIST_RELEASES, ["artist_id"])
    if "ix_artist_releases_artist_key" not in existing_indexes:
        op.create_index("ix_artist_releases_artist_key", _ARTIST_RELEASES, ["artist_key"])
    if "ix_artist_releases_release_date" not in existing_indexes:
        op.create_index("ix_artist_releases_release_date", _ARTIST_RELEASES, ["release_date"])
    if "ix_artist_releases_updated_at" not in existing_indexes:
        op.create_index("ix_artist_releases_updated_at", _ARTIST_RELEASES, ["updated_at"])

    if not _has_table(connection, _ARTIST_WATCHLIST):
        op.create_table(
            _ARTIST_WATCHLIST,
            sa.Column("artist_key", sa.String(length=255), primary_key=True),
            sa.Column("priority", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("last_enqueued_at", sa.DateTime, nullable=True),
            sa.Column("cooldown_until", sa.DateTime, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime,
                nullable=False,
                default=datetime.utcnow,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime,
                nullable=False,
                default=datetime.utcnow,
                onupdate=datetime.utcnow,
                server_default=sa.func.now(),
            ),
        )

    existing_indexes = (
        _index_names(connection, _ARTIST_WATCHLIST)
        if _has_table(connection, _ARTIST_WATCHLIST)
        else set()
    )
    if "ix_artist_watchlist_priority" not in existing_indexes:
        op.create_index(
            "ix_artist_watchlist_priority",
            _ARTIST_WATCHLIST,
            ["priority", "last_enqueued_at"],
        )


def downgrade() -> None:
    connection = op.get_bind()

    if _has_table(connection, _ARTIST_WATCHLIST):
        existing_indexes = _index_names(connection, _ARTIST_WATCHLIST)
        if "ix_artist_watchlist_priority" in existing_indexes:
            op.drop_index("ix_artist_watchlist_priority", table_name=_ARTIST_WATCHLIST)
        op.drop_table(_ARTIST_WATCHLIST)

    if _has_table(connection, _ARTIST_RELEASES):
        existing_indexes = _index_names(connection, _ARTIST_RELEASES)
        for name in (
            "ix_artist_releases_updated_at",
            "ix_artist_releases_release_date",
            "ix_artist_releases_artist_key",
            "ix_artist_releases_artist_id",
            "uq_artist_releases_source_source_id",
        ):
            if name in existing_indexes:
                op.drop_index(name, table_name=_ARTIST_RELEASES)
        op.drop_table(_ARTIST_RELEASES)

    if _has_table(connection, _ARTISTS):
        existing_indexes = _index_names(connection, _ARTISTS)
        for name in (
            "ix_artists_updated_at",
            "ix_artists_artist_key",
            "uq_artists_source_source_id",
        ):
            if name in existing_indexes:
                op.drop_index(name, table_name=_ARTISTS)
        op.drop_table(_ARTISTS)
