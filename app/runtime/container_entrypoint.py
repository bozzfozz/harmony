from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.config import DEFAULT_DOWNLOADS_DIR, DEFAULT_MUSIC_DIR, resolve_app_port
from app.config.database import get_database_url

APP_HOST = "0.0.0.0"
DEFAULT_APP_MODULE = "app.main:app"
DEFAULT_LIVE_PATH = "/live"
_MODULE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$")


@dataclass(slots=True)
class BootstrapState:
    """Mutable runtime state shared between bootstrap and launch."""

    target_uid: int
    target_gid: int


class BootstrapError(RuntimeError):
    """Raised when preparing the container runtime fails."""

    def __init__(self, message: str, *, details: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


class EntrypointError(RuntimeError):
    """Raised when building the uvicorn command fails."""

    def __init__(self, message: str, *, details: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


def log_info(prefix: str, message: str) -> None:
    print(f"[{prefix}] {message}", flush=True)


def log_failure(
    prefix: str, error: RuntimeError, *, details: Mapping[str, str] | None = None
) -> None:
    meta: list[str] = []
    if isinstance(error, BootstrapError | EntrypointError):
        meta.extend(f"{key}={value}" for key, value in error.details.items())
    if details:
        meta.extend(f"{key}={value}" for key, value in details.items())
    suffix = ""
    if meta:
        suffix = " " + ", ".join(meta)
    print(f"[{prefix}] {error}{suffix}", file=sys.stderr, flush=True)


def _normalise_payload(payload: Mapping[str, object]) -> dict[str, object]:
    normalised: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, Path):
            normalised[key] = str(value)
        else:
            normalised[key] = value
    return normalised


def log_event(
    prefix: str,
    event: str,
    *,
    level: str = "info",
    payload: Mapping[str, object] | None = None,
) -> None:
    message: dict[str, object] = {"event": event}
    if payload:
        message.update(_normalise_payload(payload))
    stream = sys.stdout if level == "info" else sys.stderr
    print(f"[{prefix}] {json.dumps(message, sort_keys=True)}", file=stream, flush=True)


def _format_umask(value: int) -> str:
    return format(value, "04o")


def _current_umask() -> int:
    previous = os.umask(0)
    os.umask(previous)
    return previous


def resolve_umask(raw_value: str | None) -> int | None:
    if raw_value is None or raw_value == "":
        return None
    try:
        resolved = int(raw_value, 8)
    except ValueError as exc:
        raise BootstrapError(
            "Invalid UMASK value", details={"value": raw_value, "error": str(exc)}
        ) from exc
    if resolved < 0:
        raise BootstrapError(
            "Invalid UMASK value", details={"value": raw_value, "error": "must be >= 0"}
        )
    return resolved


def apply_umask(resolved: int | None) -> None:
    if resolved is None:
        log_info(
            "entrypoint",
            f"UMASK not provided; using container default {_format_umask(_current_umask())}",
        )
        return
    try:
        os.umask(resolved)
    except ValueError as exc:
        raise BootstrapError(
            "Invalid UMASK value", details={"value": _format_umask(resolved), "error": str(exc)}
        ) from exc
    log_info("entrypoint", f"applied UMASK={_format_umask(resolved)}")


def parse_owner(raw_value: str | None, *, fallback: int, kind: str) -> int:
    if raw_value is None or raw_value == "":
        return fallback
    try:
        candidate = int(raw_value, 10)
    except ValueError as exc:
        raise BootstrapError(
            f"Invalid {kind} value", details={"value": raw_value, "error": str(exc)}
        ) from exc
    if candidate < 0:
        raise BootstrapError(
            f"Invalid {kind} value", details={"value": raw_value, "error": "must be non-negative"}
        )
    return candidate


def _apply_directory_ownership(path: Path, *, name: str, uid: int, gid: int) -> None:
    current_uid = os.getuid()
    current_gid = os.getgid()
    if (uid, gid) == (current_uid, current_gid):
        return
    log_info(
        "startup",
        f"adjusting ownership for {name} directory path={path} target={uid}:{gid}",
    )
    try:
        os.chown(path, uid, gid)
    except PermissionError as exc:
        raise BootstrapError(
            f"Unable to change ownership for {name} directory",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    except OSError as exc:
        raise BootstrapError(
            f"Unable to change ownership for {name} directory",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def _apply_directory_permissions(path: Path, *, name: str, umask_value: int | None) -> None:
    if umask_value is None:
        return
    desired_mode = 0o777 & ~umask_value
    log_info(
        "startup",
        f"applying permissions for {name} directory path={path} mode={oct(desired_mode)}",
    )
    try:
        path.chmod(desired_mode)
    except OSError as exc:
        raise BootstrapError(
            f"Unable to apply permissions for {name} directory",
            details={"path": str(path), "mode": oct(desired_mode), "error": str(exc)},
        ) from exc


def _verify_directory_access(path: Path, *, name: str) -> None:
    probe = path / ".harmony-startup-probe"
    try:
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        with open(probe, encoding="utf-8") as handle:
            handle.read()
    except OSError as exc:
        raise BootstrapError(
            f"Unable to verify read/write access for {name} directory",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise BootstrapError(
                f"Unable to clean startup probe for {name} directory",
                details={"path": str(path), "error": str(exc)},
            ) from exc


def ensure_directory(
    raw_path: str,
    *,
    name: str,
    uid: int,
    gid: int,
    umask_value: int | None,
) -> Path:
    log_info("startup", f"preparing {name} directory requested_path={raw_path}")
    candidate = Path(raw_path).expanduser()
    pre_existing = candidate.exists()
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BootstrapError(
            f"Unable to create {name} directory",
            details={"path": str(candidate), "error": str(exc)},
        ) from exc
    if not candidate.is_dir():
        raise BootstrapError(f"{name} path is not a directory", details={"path": str(candidate)})
    resolved = candidate.resolve()
    status = "existing" if pre_existing else "created"
    log_info("startup", f"{name} directory ready status={status} path={resolved}")
    _apply_directory_ownership(resolved, name=name, uid=uid, gid=gid)
    _apply_directory_permissions(resolved, name=name, umask_value=umask_value)
    _verify_directory_access(resolved, name=name)
    log_info("startup", f"completed verification for {name} directory path={resolved}")
    return resolved


def ensure_sqlite_database(url: str) -> None:
    log_event("startup", "sqlite.bootstrap.start", payload={"raw_url": url})
    try:
        parsed = make_url(url)
    except (ArgumentError, AttributeError) as exc:
        log_event(
            "startup",
            "sqlite.bootstrap.invalid_url",
            level="error",
            payload={"raw_url": url, "error": str(exc)},
        )
        raise BootstrapError(
            "Invalid DATABASE_URL", details={"value": url, "error": str(exc)}
        ) from exc
    if parsed.drivername not in {"sqlite", "sqlite+aiosqlite", "sqlite+pysqlite"}:
        log_event(
            "startup",
            "sqlite.bootstrap.unsupported_driver",
            level="error",
            payload={"driver": parsed.drivername, "raw_url": url},
        )
        raise BootstrapError(
            "DATABASE_URL must use a sqlite driver (sqlite+aiosqlite:/// or sqlite+pysqlite:///)",
            details={"value": url},
        )
    database_path = parsed.database
    if not database_path or database_path == ":memory:":
        log_event(
            "startup",
            "sqlite.bootstrap.skip_memory",
            payload={"driver": parsed.drivername},
        )
        return
    resolved = Path(database_path)
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()
    parent = resolved.parent
    log_event(
        "startup",
        "sqlite.bootstrap.path_resolved",
        payload={"database_path": resolved, "parent": parent},
    )
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log_event(
            "startup",
            "sqlite.bootstrap.parent_create_failed",
            level="error",
            payload={
                "parent": parent,
                "errno": getattr(exc, "errno", None),
                "error": str(exc),
            },
        )
        raise BootstrapError(
            "Unable to create database parent directory",
            details={"path": str(parent), "error": str(exc)},
        ) from exc
    if not parent.is_dir():
        log_event(
            "startup",
            "sqlite.bootstrap.parent_not_dir",
            level="error",
            payload={"parent": parent},
        )
        raise BootstrapError(
            "Database parent path is not a directory", details={"path": str(parent)}
        )
    if not os.access(parent, os.W_OK | os.X_OK):
        log_event(
            "startup",
            "sqlite.bootstrap.parent_not_writable",
            level="error",
            payload={"parent": parent, "mode": os.W_OK | os.X_OK},
        )
        raise BootstrapError(
            "Database parent directory is not writable",
            details={"path": str(parent)},
        )
    try:
        if resolved.exists():
            log_event(
                "startup",
                "sqlite.bootstrap.file_exists",
                payload={"database_path": resolved},
            )
            with open(resolved, "ab"):
                pass
        else:
            log_event(
                "startup",
                "sqlite.bootstrap.create_file",
                payload={"database_path": resolved},
            )
            resolved.touch(exist_ok=True)
    except OSError as exc:
        log_event(
            "startup",
            "sqlite.bootstrap.file_access_failed",
            level="error",
            payload={
                "database_path": resolved,
                "errno": getattr(exc, "errno", None),
                "error": str(exc),
            },
        )
        raise BootstrapError(
            "Unable to create or access sqlite database file",
            details={"path": str(resolved), "error": str(exc)},
        ) from exc
    log_event(
        "startup",
        "sqlite.bootstrap.ready",
        payload={"database_path": resolved},
    )


def ensure_database_url(env: MutableMapping[str, str]) -> str:
    fixed_url = get_database_url()
    provided = env.get("DATABASE_URL")
    if provided and provided != fixed_url:
        log_info(
            "entrypoint",
            "DATABASE_URL provided but will be overridden by Harmony default.",
        )
    env["DATABASE_URL"] = fixed_url
    log_info("entrypoint", f"using fixed DATABASE_URL={fixed_url}")
    return fixed_url


def bootstrap_environment(env: MutableMapping[str, str]) -> BootstrapState:
    umask_value = resolve_umask(env.get("UMASK"))
    apply_umask(umask_value)
    target_uid = parse_owner(env.get("PUID"), fallback=os.getuid(), kind="PUID")
    target_gid = parse_owner(env.get("PGID"), fallback=os.getgid(), kind="PGID")
    umask_rendered = env.get("UMASK", "default")
    log_info(
        "entrypoint",
        (
            "bootstrap parameters "
            f"target_uid={target_uid} target_gid={target_gid} umask={umask_rendered}"
        ),
    )
    database_url = ensure_database_url(env)
    directories = {
        "downloads": env.get("DOWNLOADS_DIR") or DEFAULT_DOWNLOADS_DIR,
        "music": env.get("MUSIC_DIR") or DEFAULT_MUSIC_DIR,
    }
    for label, raw_path in directories.items():
        ensured = ensure_directory(
            raw_path,
            name=label,
            uid=target_uid,
            gid=target_gid,
            umask_value=umask_value,
        )
        log_info(
            "startup", f"ensured {label} directory path={ensured} owner={target_uid}:{target_gid}"
        )
    ensure_sqlite_database(database_url)
    return BootstrapState(target_uid=target_uid, target_gid=target_gid)


def combine_extra_args(argv: Sequence[str], extra_env: str | None) -> list[str]:
    extras: list[str] = []
    if extra_env:
        extras.extend(shlex.split(extra_env))
    extras.extend(argv)
    if not extras:
        return []
    if extras[0] == "uvicorn":
        return extras[1:]
    if (
        len(extras) >= 3
        and extras[0].startswith("python")
        and extras[1] == "-m"
        and extras[2] == "uvicorn"
    ):
        return extras[3:]
    return extras


def sanitize_extra_args(raw_args: Sequence[str]) -> list[str]:
    sanitized: list[str] = []
    index = 0
    total = len(raw_args)
    while index < total:
        token = raw_args[index]
        if not token:
            index += 1
            continue
        if token in {"--host", "--port"}:
            index += 2
            continue
        if token.startswith("-"):
            sanitized.append(token)
            index += 1
            continue
        if sanitized:
            if _MODULE_PATTERN.match(token):
                raise EntrypointError(
                    (
                        "Unsupported module override via startup arguments. "
                        "Configure APP_MODULE instead."
                    ),
                    details={"value": token},
                )
            sanitized.append(token)
            index += 1
            continue
        raise EntrypointError(
            "Startup arguments must be uvicorn options. "
            "Provide additional flags via UVICORN_EXTRA_ARGS."
        )
    return sanitized


def build_uvicorn_command(port: int, module: str, extras: Sequence[str]) -> list[str]:
    python_exec = sys.executable or "python"
    base_command = [
        python_exec,
        "-m",
        "uvicorn",
        module,
        "--host",
        APP_HOST,
        "--port",
        str(port),
    ]
    return base_command + list(extras)


def drop_privileges(target_uid: int, target_gid: int) -> None:
    current_uid = os.getuid()
    current_gid = os.getgid()
    if (current_uid, current_gid) == (target_uid, target_gid):
        log_info("entrypoint", f"running as requested identity {current_uid}:{current_gid}")
        return
    if current_uid != 0:
        raise EntrypointError(
            "insufficient permissions to change identity",
            details={
                "current": f"{current_uid}:{current_gid}",
                "target": f"{target_uid}:{target_gid}",
            },
        )
    log_info(
        "entrypoint",
        f"switching identity {current_uid}:{current_gid} -> {target_uid}:{target_gid}",
    )
    try:
        if hasattr(os, "setgroups"):
            os.setgroups([target_gid])
        os.setgid(target_gid)
        os.setuid(target_uid)
    except OSError as exc:
        raise EntrypointError(
            "failed to drop privileges",
            details={"target": f"{target_uid}:{target_gid}", "error": str(exc)},
        ) from exc
    final_uid = os.getuid()
    final_gid = os.getgid()
    if (final_uid, final_gid) != (target_uid, target_gid):
        raise EntrypointError(
            "privilege drop verification failed",
            details={
                "expected": f"{target_uid}:{target_gid}",
                "actual": f"{final_uid}:{final_gid}",
            },
        )
    log_info("entrypoint", f"switched identity to {final_uid}:{final_gid}")


def launch_application(
    argv: Sequence[str], env: MutableMapping[str, str], state: BootstrapState
) -> None:
    log_info("entrypoint", f"requested runtime identity {state.target_uid}:{state.target_gid}")
    drop_privileges(state.target_uid, state.target_gid)
    extras = sanitize_extra_args(combine_extra_args(argv, env.get("UVICORN_EXTRA_ARGS")))
    try:
        port = resolve_app_port()
    except Exception as exc:  # pragma: no cover - defensive guard for runtime env
        raise EntrypointError("Failed to resolve APP_PORT", details={"error": str(exc)}) from exc
    env["APP_PORT"] = str(port)
    log_info("entrypoint", f"resolved APP_PORT={port}")
    module = env.get("APP_MODULE", DEFAULT_APP_MODULE)
    command = build_uvicorn_command(port, module, extras)
    live_path = env.get("APP_LIVE_PATH", DEFAULT_LIVE_PATH)
    python_version = sys.version.split()[0]
    log_info("entrypoint", f"python executable: {command[0]}")
    log_info("entrypoint", f"python version: {python_version}")
    python_path = env.get("PYTHONPATH")
    if python_path:
        log_info("entrypoint", f"PYTHONPATH={python_path}")
    if extras:
        rendered = " ".join(shlex.quote(arg) for arg in extras)
        log_info("entrypoint", f"uvicorn extra args: {rendered}")
    cwd = os.getcwd()
    log_info(
        "entrypoint",
        (
            "runtime summary "
            f"host={APP_HOST} port={port} module={module} python={python_version} cwd={cwd}"
        ),
    )
    log_info(
        "entrypoint",
        f"starting uvicorn for {module} on {APP_HOST}:{port} (live={live_path})",
    )
    try:
        os.execvp(command[0], command)
    except OSError as exc:
        raise EntrypointError(
            "Failed to exec uvicorn", details={"command": command[0], "error": str(exc)}
        ) from exc


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    env: MutableMapping[str, str] = os.environ
    try:
        state = bootstrap_environment(env)
    except BootstrapError as exc:
        log_failure("startup", exc)
        raise SystemExit(1) from exc
    try:
        launch_application(args, env, state)
    except EntrypointError as exc:
        log_failure("entrypoint", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
