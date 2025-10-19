"""Lightweight schema migration helpers for SQLite deployments."""

from __future__ import annotations

import logging

from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)


def apply_schema_migrations(engine: Engine) -> None:
    """Apply idempotent schema adjustments for legacy databases."""

    with engine.begin() as connection:
        _ensure_playlist_metadata_column(connection)


def _ensure_playlist_metadata_column(connection: Connection) -> None:
    inspector = inspect(connection)
    try:
        columns = inspector.get_columns("playlists")
    except Exception:  # pragma: no cover - defensive guard
        logger.debug("Unable to inspect playlists table for migrations", exc_info=True)
        return

    column_names = {column.get("name") for column in columns}
    if "metadata" in column_names:
        return

    logger.info("Adding playlists.metadata column via migration")
    connection.execute(text("ALTER TABLE playlists ADD COLUMN metadata JSON"))
