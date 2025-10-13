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
from __future__ import annotations

import os
import re
import shlex
import sys
from typing import List

from app.config import resolve_app_port


APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_MODULE = os.environ.get("APP_MODULE", "app.main:app")
LIVE_PATH = os.environ.get("APP_LIVE_PATH", "/live")
_MODULE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$")


def _combine_extra_args(argv: List[str]) -> List[str]:
    extras: List[str] = []
    extra_env = os.environ.get("UVICORN_EXTRA_ARGS")
    if extra_env:
        extras.extend(shlex.split(extra_env))
    extras.extend(argv)
    if not extras:
        return []
    if extras[0] == "uvicorn":
        return extras[1:]
    if len(extras) >= 3 and extras[0].startswith("python") and extras[1] == "-m" and extras[2] == "uvicorn":
        return extras[3:]
    return extras


def _sanitize_extra_args(raw_args: List[str]) -> List[str]:
    sanitized: List[str] = []
    index = 0
    total = len(raw_args)
    while index < total:
        token = raw_args[index]
        if not token:
            index += 1
            continue
        if token in {"--host", "--port"}:
            index += 1
            if index < total:
                index += 1
            continue
        if token.startswith("-"):
            sanitized.append(token)
            index += 1
            continue
        if sanitized:
            if _MODULE_PATTERN.match(token):
                print(
                    f"[entrypoint] Unsupported module override '{token}'. Configure APP_MODULE instead.",
                    file=sys.stderr,
                )
                sys.exit(1)
            sanitized.append(token)
            index += 1
            continue
        print(
            "[entrypoint] Startup arguments must be uvicorn options. "
            "Provide additional flags via UVICORN_EXTRA_ARGS.",
            file=sys.stderr,
        )
        sys.exit(1)
    return sanitized


def _resolve_port() -> int:
    try:
        port = resolve_app_port()
    except Exception as exc:  # pragma: no cover - handled in runtime
        print(f"[entrypoint] Failed to resolve APP_PORT: {exc}", file=sys.stderr)
        sys.exit(1)
    os.environ["APP_PORT"] = str(port)
    return port


def main(argv: List[str]) -> None:
    extras = _sanitize_extra_args(_combine_extra_args(argv))
    port = _resolve_port()
    print(f"[entrypoint] resolved APP_PORT={port}")
    python_exec = sys.executable or "python"
    base_command = [python_exec, "-m", "uvicorn", APP_MODULE, "--host", APP_HOST, "--port", str(port)]
    command = base_command + extras

    print(f"[entrypoint] python executable: {python_exec}")
    python_path = os.environ.get("PYTHONPATH")
    if python_path:
        print(f"[entrypoint] PYTHONPATH={python_path}")
    if extras:
        rendered = " ".join(shlex.quote(arg) for arg in extras)
        print(f"[entrypoint] uvicorn extra args: {rendered}")
    print(
        f"[entrypoint] starting uvicorn for {APP_MODULE} on {APP_HOST}:{port} (live={LIVE_PATH})"
    )

    try:
        os.execvp(command[0], command)
    except OSError as exc:  # pragma: no cover - runtime behaviour
        print(f"[entrypoint] Failed to exec {command[0]}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
PYTHON
