from __future__ import annotations

import os
from pathlib import Path
import subprocess


def test_docker_entrypoint_executes_with_uvicorn_help(tmp_path: Path) -> None:
    script_path = Path("scripts/docker-entrypoint.sh").resolve()
    project_root = Path(__file__).resolve().parents[2]

    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    database_path = tmp_path / "harmony.db"

    env = os.environ.copy()
    env.update(
        {
            "DOWNLOADS_DIR": str(downloads_dir),
            "MUSIC_DIR": str(music_dir),
            "DATABASE_URL": f"sqlite+aiosqlite:///{database_path}",
            "PUID": str(os.getuid()),
            "PGID": str(os.getgid()),
            "UVICORN_EXTRA_ARGS": "--help",
        }
    )

    result = subprocess.run(
        [str(script_path), "--help"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Usage: python -m uvicorn" in result.stdout
