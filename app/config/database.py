"""Database configuration helpers for Harmony."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from app.runtime.paths import SQLITE_DATABASE_URL, SQLITE_DB_PATH, ensure_sqlite_db

HARMONY_DATABASE_FILE: Final[Path] = SQLITE_DB_PATH
HARMONY_DATABASE_URL: Final[str] = SQLITE_DATABASE_URL


def get_database_url() -> str:
    """Return the canonical SQLite database URL for Harmony."""

    ensure_sqlite_db(HARMONY_DATABASE_FILE)
    return HARMONY_DATABASE_URL


__all__ = ["HARMONY_DATABASE_FILE", "HARMONY_DATABASE_URL", "get_database_url"]
