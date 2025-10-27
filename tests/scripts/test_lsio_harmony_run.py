from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _write_stub(stub_dir: Path, name: str, body: str) -> None:
    script_path = stub_dir / name
    script_path.write_text("#!/bin/sh\n" + body + ("" if body.endswith("\n") else "\n"))
    script_path.chmod(0o755)


def test_lsio_run_preserves_preconfigured_database_url(tmp_path: Path) -> None:
    script_path = Path("docker/lsio/root/etc/services.d/harmony/run").resolve()
    project_root = Path(__file__).resolve().parents[2]

    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()

    _write_stub(stub_dir, "getent", "case \"$1\" in\n  passwd|group) exit 2 ;;\n  *) exit 0 ;;\nesac\n")
    for command in ("addgroup", "adduser", "delgroup", "deluser", "mkdir", "chown"):
        _write_stub(stub_dir, command, "exit 0\n")

    _write_stub(
        stub_dir,
        "s6-setuidgid",
        "if [ -n \"${ENV_CAPTURE_PATH:-}\" ]; then\n  printf '%s\n' \"${SQLALCHEMY_DATABASE_URL:-}\" > \"${ENV_CAPTURE_PATH}\"\nfi\nexit 0\n",
    )

    capture_file = tmp_path / "dsn.txt"

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{stub_dir}:{env['PATH']}",
            "PUID": str(os.getuid()),
            "PGID": str(os.getgid()),
            "TZ": "Etc/UTC",
            "UMASK": "022",
            "SQLALCHEMY_DATABASE_URL": "postgresql://example/harmony",
            "ENV_CAPTURE_PATH": str(capture_file),
        }
    )

    result = subprocess.run(
        ["bash", str(script_path)],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert capture_file.read_text().strip() == "postgresql://example/harmony"
