"""Canonical filesystem locations for Harmony runtime state."""

from __future__ import annotations

import os
from pathlib import Path

CONFIG_DIR = Path("/config")
DOWNLOADS_DIR = Path("/downloads")
MUSIC_DIR = Path("/music")
SQLITE_DB_PATH = CONFIG_DIR / "harmony.db"
SQLITE_DATABASE_URL = f"sqlite:///{SQLITE_DB_PATH}"


class StorageError(RuntimeError):
    """Raised when Harmony cannot prepare its storage layout."""


def ensure_dir(path: Path) -> None:
    """Ensure that *path* exists as a directory."""

    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - defensive guard
        raise StorageError(f"Unable to create directory {path}: {exc}") from exc
    if not path.is_dir():
        raise StorageError(f"{path} exists but is not a directory")


def ensure_sqlite_db(path: Path) -> None:
    """Create an empty SQLite database file at *path* if missing."""

    ensure_dir(path.parent)
    try:
        if not path.exists():
            path.touch(exist_ok=True)
    except OSError as exc:  # pragma: no cover - defensive guard
        raise StorageError(f"Unable to create sqlite database at {path}: {exc}") from exc


def validate_permissions(path: Path) -> None:
    """Verify that *path* is a writable directory."""

    ensure_dir(path)
    probe = path / ".harmony-permission-check"
    try:
        with probe.open("wb") as handle:
            handle.write(b"ok")
            handle.flush()
            os.fsync(handle.fileno())
        with probe.open("rb") as handle:
            handle.read()
    except OSError as exc:
        raise StorageError(f"Directory {path} is not writable: {exc}") from exc
    finally:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass


def bootstrap_storage() -> None:
    """Prepare Harmony's required storage directories and database file."""

    ensure_dir(CONFIG_DIR)
    ensure_dir(DOWNLOADS_DIR)
    ensure_dir(MUSIC_DIR)
    ensure_sqlite_db(SQLITE_DB_PATH)


__all__ = [
    "CONFIG_DIR",
    "DOWNLOADS_DIR",
    "MUSIC_DIR",
    "SQLITE_DB_PATH",
    "SQLITE_DATABASE_URL",
    "StorageError",
    "bootstrap_storage",
    "ensure_dir",
    "ensure_sqlite_db",
    "validate_permissions",
]
