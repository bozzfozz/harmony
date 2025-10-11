import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import override_runtime_env
from app.db import reset_engine_for_tests


@pytest.fixture(autouse=True)
def _test_environment(tmp_path: Path) -> Iterator[None]:
    data_dir = tmp_path / "data"
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    oauth_state_dir = tmp_path / "oauth_state"
    for directory in (data_dir, downloads_dir, music_dir, oauth_state_dir):
        directory.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "harmony.db"

    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("SPOTIFY_CLIENT_ID", "test-client")
    os.environ.setdefault("SPOTIFY_CLIENT_SECRET", "test-secret")
    os.environ.setdefault("OAUTH_SPLIT_MODE", "false")
    os.environ.setdefault("DOWNLOADS_DIR", str(downloads_dir))
    os.environ.setdefault("MUSIC_DIR", str(music_dir))
    os.environ.setdefault("OAUTH_STATE_DIR", str(oauth_state_dir))
    os.environ.setdefault("SLSKD_HOST", "127.0.0.1")
    os.environ.setdefault("SLSKD_PORT", "5030")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    override_runtime_env(None)
    reset_engine_for_tests()
    try:
        yield
    finally:
        reset_engine_for_tests()
        override_runtime_env(None)
        os.environ.pop("DB_RESET", None)
