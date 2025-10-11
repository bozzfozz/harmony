from pathlib import Path

from app.config import override_runtime_env
from app.db import init_db, reset_engine_for_tests


def test_init_db_creates_sqlite_file(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "harmony.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    monkeypatch.setenv("APP_ENV", "dev")

    reset_engine_for_tests()
    override_runtime_env(None)
    try:
        init_db()

        assert db_file.exists()
        assert db_file.read_bytes().startswith(b"SQLite format 3")
    finally:
        reset_engine_for_tests()


def test_db_reset_recreates_file(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "harmony.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    monkeypatch.setenv("APP_ENV", "dev")

    reset_engine_for_tests()
    try:
        init_db()
        db_file.write_bytes(b"junk")

        monkeypatch.setenv("DB_RESET", "1")
        override_runtime_env(None)
        init_db()

        contents = db_file.read_bytes()
        assert contents.startswith(b"SQLite format 3")
    finally:
        reset_engine_for_tests()
