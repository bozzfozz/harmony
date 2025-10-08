"""Create base schema"""

from __future__ import annotations

from typing import Any, Dict, Iterable

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# Import models to populate metadata
from app import models  # noqa: F401
from app.db import Base

revision = "7c9bdb5e1a3d"
down_revision = None
branch_labels = None
depends_on = None


def _download_column_definitions() -> Dict[str, sa.Column[Any]]:
    return {
        "spotify_track_id": sa.Column("spotify_track_id", sa.String(length=128), nullable=True),
        "spotify_album_id": sa.Column("spotify_album_id", sa.String(length=128), nullable=True),
        "artwork_path": sa.Column("artwork_path", sa.String(length=2048), nullable=True),
        "artwork_url": sa.Column("artwork_url", sa.String(length=2048), nullable=True),
        "artwork_status": sa.Column(
            "artwork_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        "has_artwork": sa.Column(
            "has_artwork",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        "genre": sa.Column("genre", sa.String(length=255), nullable=True),
        "composer": sa.Column("composer", sa.String(length=255), nullable=True),
        "producer": sa.Column("producer", sa.String(length=255), nullable=True),
        "isrc": sa.Column("isrc", sa.String(length=64), nullable=True),
        "copyright": sa.Column("copyright", sa.String(length=512), nullable=True),
        "organized_path": sa.Column("organized_path", sa.String(length=2048), nullable=True),
        "retry_count": sa.Column(
            "retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        "next_retry_at": sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        "last_error": sa.Column("last_error", sa.Text(), nullable=True),
    }


def _ingest_item_column_definitions() -> Dict[str, sa.Column[Any]]:
    return {
        "spotify_track_id": sa.Column("spotify_track_id", sa.String(length=128), nullable=True),
        "spotify_album_id": sa.Column("spotify_album_id", sa.String(length=128), nullable=True),
        "isrc": sa.Column("isrc", sa.String(length=64), nullable=True),
    }


def _ensure_indexes(table: str, expected: Dict[str, Iterable[str]]) -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = {index["name"] for index in inspector.get_indexes(table)}
    for name, columns in expected.items():
        if name not in existing:
            op.create_index(name, table, list(columns))


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)

    inspector = inspect(bind)

    downloads_columns = {column["name"] for column in inspector.get_columns("downloads")}
    for name, column in _download_column_definitions().items():
        if name not in downloads_columns:
            op.add_column("downloads", column)

    ingest_columns = {column["name"] for column in inspector.get_columns("ingest_items")}
    for name, column in _ingest_item_column_definitions().items():
        if name not in ingest_columns:
            op.add_column("ingest_items", column)

    _ensure_indexes(
        "downloads",
        {
            "ix_downloads_state": ["state"],
            "ix_downloads_created_at": ["created_at"],
            "ix_downloads_spotify_track_id": ["spotify_track_id"],
            "ix_downloads_spotify_album_id": ["spotify_album_id"],
        },
    )
    _ensure_indexes(
        "ingest_items",
        {
            "ix_ingest_items_job_state": ["job_id", "state"],
            "ix_ingest_items_job_hash": ["job_id", "dedupe_hash"],
            "ix_ingest_items_spotify_track_id": ["spotify_track_id"],
            "ix_ingest_items_spotify_album_id": ["spotify_album_id"],
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=True)
