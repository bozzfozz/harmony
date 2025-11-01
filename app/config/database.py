"""Database configuration helpers."""
from pathlib import Path
from typing import Final

DB_FILE: Final[Path] = Path("/config/harmony.db")
DB_URL: Final[str] = f"sqlite:///{DB_FILE}"

def get_database_url() -> str:
    """Return the SQLite database URL, ensuring the directory exists."""
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    return DB_URL
