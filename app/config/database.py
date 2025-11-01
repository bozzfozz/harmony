"""Database configuration helpers for Harmony."""

from __future__ import annotations

from pathlib import Path
from typing import Final

HARMONY_DATABASE_FILE: Final[Path] = Path("/config/harmony.db")
HARMONY_DATABASE_URL: Final[str] = f"sqlite+aiosqlite:///{HARMONY_DATABASE_FILE}"


def get_database_url() -> str:
    """Return the canonical SQLite database URL for Harmony."""

    HARMONY_DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    return HARMONY_DATABASE_URL


__all__ = ["HARMONY_DATABASE_FILE", "HARMONY_DATABASE_URL", "get_database_url"]
