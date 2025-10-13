#!/usr/bin/env sh
set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
  export DATABASE_URL="sqlite+aiosqlite:///data/harmony.db"
  echo "DATABASE_URL not provided; using ${DATABASE_URL}."
fi

case "${DATABASE_URL}" in
  sqlite+aiosqlite://*|sqlite+pysqlite://*|sqlite://*)
    ;;
  *)
    echo "Error: DATABASE_URL must use a sqlite driver (sqlite+aiosqlite:/// or sqlite+pysqlite:///)." >&2
    exit 1
    ;;
esac

python3 <<'PYTHON'
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url


def _fail(message: str, *, details: dict[str, str] | None = None) -> None:
    meta = ""
    if details:
        meta = " " + ", ".join(f"{key}={value}" for key, value in details.items())
    print(f"[startup] {message}{meta}", file=sys.stderr)
    sys.exit(1)


url = make_url(os.environ["DATABASE_URL"])
path = url.database
if path and path != ":memory:":
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()
    parent = resolved.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _fail(
            "Unable to create database parent directory",
            details={"path": str(parent), "error": str(exc)},
        )
    if not parent.is_dir():
        _fail("Database parent path is not a directory", details={"path": str(parent)})
    if not os.access(parent, os.W_OK | os.X_OK):
        _fail(
            "Database parent directory is not writable",
            details={"path": str(parent)},
        )
    try:
        if resolved.exists():
            with open(resolved, "ab"):
                pass
        else:
            resolved.touch(exist_ok=True)
    except OSError as exc:
        _fail(
            "Unable to create or access sqlite database file",
            details={"path": str(resolved), "error": str(exc)},
        )
PYTHON

exec python3 - "$@" <<'PYTHON'
import os
import sys
from typing import List

from app.config import resolve_app_port


APP_HOST = "0.0.0.0"


def _needs_uvicorn_binding(argv: List[str]) -> tuple[bool, int]:
    if not argv:
        return True, 0
    first = argv[0]
    if first == "uvicorn":
        return True, 0
    if len(argv) >= 3 and first.startswith("python") and argv[1] == "-m" and argv[2] == "uvicorn":
        return True, 3
    return False, 0


def _strip_host_port(argv: List[str], offset: int) -> List[str]:
    sanitized: List[str] = list(argv[:offset])
    index = offset
    total = len(argv)
    while index < total:
        candidate = argv[index]
        if candidate in {"--host", "--port"}:
            index += 1
            if index < total:
                index += 1
            continue
        sanitized.append(candidate)
        index += 1
    return sanitized


def _resolve_command(argv: List[str]) -> List[str]:
    port = resolve_app_port()
    os.environ["APP_PORT"] = str(port)
    print(f"[entrypoint] APP_PORT resolved to {port}")
    needs_binding, offset = _needs_uvicorn_binding(argv)
    if not needs_binding:
        return argv
    sanitized = _strip_host_port(argv, offset)
    sanitized.extend(["--host", APP_HOST, "--port", str(port)])
    print(f"[entrypoint] Enforcing uvicorn bind on {APP_HOST}:{port}")
    return sanitized


command = _resolve_command(sys.argv[1:])
if not command:
    command = ["uvicorn", "app.main:app", "--host", APP_HOST, "--port", os.environ["APP_PORT"]]
    print("[entrypoint] Defaulting to uvicorn app.main:app")

os.execvp(command[0], command)
PYTHON
