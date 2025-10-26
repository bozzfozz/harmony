#!/usr/bin/env sh
set -euo pipefail

log_info() {
  printf '[entrypoint] %s\n' "$1"
}

if [ -n "${UMASK:-}" ]; then
  log_info "validating UMASK=${UMASK}"
  if ! umask "$UMASK" 2>/dev/null; then
    echo "Error: Invalid UMASK value '$UMASK'." >&2
    exit 1
  fi
  log_info "applied UMASK=$(umask)"
else
  log_info "UMASK not provided; using container default $(umask)"
fi

if [ -z "${DATABASE_URL:-}" ]; then
  export DATABASE_URL="sqlite+aiosqlite:///data/harmony.db"
  log_info "DATABASE_URL not provided; using ${DATABASE_URL}."
else
  log_info "received DATABASE_URL=${DATABASE_URL}"
fi

log_info "starting filesystem and database bootstrap"

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

from app.config import DEFAULT_DOWNLOADS_DIR, DEFAULT_MUSIC_DIR


def _fail(message: str, *, details: dict[str, str] | None = None) -> None:
    meta = ""
    if details:
        meta = " " + ", ".join(f"{key}={value}" for key, value in details.items())
    print(f"[startup] {message}{meta}", file=sys.stderr)
    sys.exit(1)


def _parse_owner(value: str | None, *, kind: str, fallback: int) -> int:
    if value is None or value == "":
        return fallback
    try:
        candidate = int(value, 10)
    except ValueError as exc:  # pragma: no cover - config validation at runtime
        _fail(f"Invalid {kind} value", details={"value": value, "error": str(exc)})
    if candidate < 0:
        _fail(f"Invalid {kind} value", details={"value": value, "error": "must be non-negative"})
    return candidate


def _parse_umask(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        resolved = int(value, 8)
    except ValueError as exc:  # pragma: no cover - config validation at runtime
        _fail("Invalid UMASK value", details={"value": value, "error": str(exc)})
    if resolved < 0:
        _fail("Invalid UMASK value", details={"value": value, "error": "must be >= 0"})
    return resolved


def _ensure_directory(
    raw_path: str,
    *,
    name: str,
    uid: int,
    gid: int,
    umask_value: int | None,
) -> Path:
    print(
        f"[startup] preparing {name} directory requested_path={raw_path}",
        flush=True,
    )
    candidate = Path(raw_path).expanduser()
    pre_existing = candidate.exists()
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _fail(
            f"Unable to create {name} directory",
            details={"path": str(candidate), "error": str(exc)},
        )
    if not candidate.is_dir():
        _fail(f"{name} path is not a directory", details={"path": str(candidate)})
    resolved = candidate.resolve()
    status = "existing" if pre_existing else "created"
    print(
        f"[startup] {name} directory ready status={status} path={resolved}",
        flush=True,
    )
    if (uid, gid) != (os.getuid(), os.getgid()):
        print(
            f"[startup] adjusting ownership for {name} directory path={resolved} target={uid}:{gid}",
            flush=True,
        )
        try:
            os.chown(resolved, uid, gid)
        except PermissionError as exc:
            _fail(
                f"Unable to change ownership for {name} directory",
                details={"path": str(resolved), "error": str(exc)},
            )
        except OSError as exc:
            _fail(
                f"Unable to change ownership for {name} directory",
                details={"path": str(resolved), "error": str(exc)},
            )
    if umask_value is not None:
        desired_mode = 0o777 & ~umask_value
        print(
            f"[startup] applying permissions for {name} directory path={resolved} mode={oct(desired_mode)}",
            flush=True,
        )
        try:
            resolved.chmod(desired_mode)
        except OSError as exc:
            _fail(
                f"Unable to apply permissions for {name} directory",
                details={
                    "path": str(resolved),
                    "mode": oct(desired_mode),
                    "error": str(exc),
                },
            )
    probe = resolved / ".harmony-startup-probe"
    try:
        print(
            f"[startup] verifying read/write access for {name} directory path={resolved}",
            flush=True,
        )
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        with open(probe, "r", encoding="utf-8") as handle:
            handle.read()
    except OSError as exc:
        _fail(
            f"Unable to verify read/write access for {name} directory",
            details={"path": str(resolved), "error": str(exc)},
        )
    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            _fail(
                f"Unable to clean startup probe for {name} directory",
                details={"path": str(resolved), "error": str(exc)},
            )
    print(
        f"[startup] completed verification for {name} directory path={resolved}",
        flush=True,
    )
    return resolved


umask_value = _parse_umask(os.environ.get("UMASK"))
target_uid = _parse_owner(os.environ.get("PUID"), kind="PUID", fallback=os.getuid())
target_gid = _parse_owner(os.environ.get("PGID"), kind="PGID", fallback=os.getgid())

print(
    "[startup] bootstrap parameters "
    f"target_uid={target_uid} target_gid={target_gid} umask={os.environ.get('UMASK', 'default')}",
    flush=True,
)

directories = {
    "downloads": os.environ.get("DOWNLOADS_DIR") or DEFAULT_DOWNLOADS_DIR,
    "music": os.environ.get("MUSIC_DIR") or DEFAULT_MUSIC_DIR,
}

for label, raw in directories.items():
    ensured = _ensure_directory(raw, name=f"{label}", uid=target_uid, gid=target_gid, umask_value=umask_value)
    print(
        "[startup] ensured %s directory path=%s owner=%s:%s"
        % (label, ensured, target_uid, target_gid),
        flush=True,
    )

url = make_url(os.environ["DATABASE_URL"])
path = url.database
if path and path != ":memory:":
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()
    parent = resolved.parent
    print(
        f"[startup] ensuring sqlite database path={resolved}",
        flush=True,
    )
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
    print(
        f"[startup] database directory ready path={parent}",
        flush=True,
    )
    try:
        if resolved.exists():
            print(
                f"[startup] found existing sqlite database path={resolved}",
                flush=True,
            )
            with open(resolved, "ab"):
                pass
        else:
            print(
                f"[startup] creating sqlite database file path={resolved}",
                flush=True,
            )
            resolved.touch(exist_ok=True)
    except OSError as exc:
        _fail(
            "Unable to create or access sqlite database file",
            details={"path": str(resolved), "error": str(exc)},
        )
    print(
        f"[startup] sqlite database ready path={resolved}",
        flush=True,
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


APP_HOST = "0.0.0.0"
APP_MODULE = os.environ.get("APP_MODULE", "app.main:app")
LIVE_PATH = os.environ.get("APP_LIVE_PATH", "/live")
_MODULE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$")


def _parse_owner(value: str | None, *, kind: str, fallback: int) -> int:
    if value is None or value == "":
        return fallback
    try:
        candidate = int(value, 10)
    except ValueError as exc:  # pragma: no cover - config validation at runtime
        print(
            f"[entrypoint] Invalid {kind} value '{value}': {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    if candidate < 0:
        print(
            f"[entrypoint] Invalid {kind} value '{value}': must be non-negative",
            file=sys.stderr,
        )
        sys.exit(1)
    return candidate


def _drop_privileges(target_uid: int, target_gid: int) -> None:
    current_uid = os.getuid()
    current_gid = os.getgid()
    if (current_uid, current_gid) == (target_uid, target_gid):
        print(
            f"[entrypoint] running as requested identity {current_uid}:{current_gid}"
        )
        return
    if current_uid != 0:
        print(
            "[entrypoint] insufficient permissions to change identity "
            f"{current_uid}:{current_gid} -> {target_uid}:{target_gid}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"[entrypoint] switching identity {current_uid}:{current_gid} -> {target_uid}:{target_gid}"
    )
    try:
        if hasattr(os, "setgroups"):
            os.setgroups([target_gid])
    except OSError as exc:
        print(
            "[entrypoint] failed to drop supplementary groups "
            f"for {target_gid}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        os.setgid(target_gid)
    except OSError as exc:
        print(
            f"[entrypoint] failed to setgid({target_gid}): {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        os.setuid(target_uid)
    except OSError as exc:
        print(
            f"[entrypoint] failed to setuid({target_uid}): {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    final_uid = os.getuid()
    final_gid = os.getgid()
    if (final_uid, final_gid) != (target_uid, target_gid):
        print(
            "[entrypoint] privilege drop verification failed: "
            f"expected {target_uid}:{target_gid}, got {final_uid}:{final_gid}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        f"[entrypoint] switched identity to {final_uid}:{final_gid}")


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
    target_uid = _parse_owner(
        os.environ.get("PUID"), kind="PUID", fallback=os.getuid()
    )
    target_gid = _parse_owner(
        os.environ.get("PGID"), kind="PGID", fallback=os.getgid()
    )
    print(
        f"[entrypoint] requested runtime identity {target_uid}:{target_gid}",
        flush=True,
    )
    _drop_privileges(target_uid, target_gid)
    extras = _sanitize_extra_args(_combine_extra_args(argv))
    port = _resolve_port()
    print(f"[entrypoint] resolved APP_PORT={port}", flush=True)
    python_exec = sys.executable or "python"
    python_version = sys.version.split()[0]
    base_command = [
        python_exec,
        "-m",
        "uvicorn",
        APP_MODULE,
        "--host",
        APP_HOST,
        "--port",
        str(port),
    ]
    command = base_command + extras
    cwd = os.getcwd()

    print(f"[entrypoint] python executable: {python_exec}", flush=True)
    print(f"[entrypoint] python version: {python_version}", flush=True)
    python_path = os.environ.get("PYTHONPATH")
    if python_path:
        print(f"[entrypoint] PYTHONPATH={python_path}", flush=True)
    if extras:
        rendered = " ".join(shlex.quote(arg) for arg in extras)
        print(f"[entrypoint] uvicorn extra args: {rendered}", flush=True)
    print(
        "[entrypoint] runtime summary host=%s port=%s module=%s python=%s cwd=%s"
        % (APP_HOST, port, APP_MODULE, python_version, cwd),
        flush=True,
    )
    print(
        f"[entrypoint] starting uvicorn for {APP_MODULE} on {APP_HOST}:{port} (live={LIVE_PATH})",
        flush=True,
    )

    try:
        os.execvp(command[0], command)
    except OSError as exc:  # pragma: no cover - runtime behaviour
        print(f"[entrypoint] Failed to exec {command[0]}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
PYTHON
