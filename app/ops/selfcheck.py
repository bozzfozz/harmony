"""Operational readiness and startup self-check utilities."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import socket
import sqlite3
import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.config import (
    DEFAULT_DB_URL_DEV,
    DEFAULT_DB_URL_PROD,
    DEFAULT_DB_URL_TEST,
    HdmConfig,
    load_runtime_env,
)
from app.hdm.idempotency import SQLITE_CREATE_TABLE, SQLITE_DELETE, SQLITE_INSERT
from app.logging import get_logger

logger = get_logger(__name__)

# Exit codes aligned with ``sysexits`` for observability and automation.
EX_CONFIG = getattr(os, "EX_CONFIG", 78)
EX_OSERR = getattr(os, "EX_OSERR", 71)
EX_UNAVAILABLE = getattr(os, "EX_UNAVAILABLE", 69)
EX_SOFTWARE = getattr(os, "EX_SOFTWARE", 70)

_SLSKD_BASE_URL_KEYS = ("SLSKD_BASE_URL", "SLSKD_URL")

_REQUIRED_ENV_BASE = (
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "OAUTH_SPLIT_MODE",
    "DOWNLOADS_DIR",
    "MUSIC_DIR",
)

_OPTIONAL_ENV_KEYS = ("UMASK", "PUID", "PGID")

_DEFAULT_PORT_BY_SCHEME = {"http": 80, "https": 443}


def _resolve_profile(env: Mapping[str, Any]) -> str:
    raw = str(env.get("APP_ENV") or env.get("ENVIRONMENT") or "").strip()
    if not raw and env.get("PYTEST_CURRENT_TEST"):
        raw = "test"
    normalized = raw.lower()
    aliases = {
        "development": "dev",
        "local": "dev",
        "production": "prod",
        "live": "prod",
        "stage": "staging",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"dev", "staging", "prod", "test"}:
        return "dev"
    return normalized


def _default_database_url(profile: str) -> str:
    if profile in {"prod", "staging"}:
        return DEFAULT_DB_URL_PROD
    if profile == "test":
        return DEFAULT_DB_URL_TEST
    return DEFAULT_DB_URL_DEV


@dataclass(slots=True)
class ReadyIssue:
    """Represents a single readiness failure."""

    component: str
    message: str
    exit_code: int
    details: MutableMapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReadyReport:
    """Aggregated readiness information for the API and startup guards."""

    status: str
    checks: MutableMapping[str, Any]
    issues: list[ReadyIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self, *, verbose: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if verbose or not self.ok:
            payload["checks"] = self.checks
            if not self.ok:
                payload["issues"] = [
                    {
                        "component": issue.component,
                        "message": issue.message,
                        "exit_code": issue.exit_code,
                        "details": dict(issue.details),
                    }
                    for issue in self.issues
                ]
        return payload


def _normalise_env(runtime_env: Mapping[str, Any] | None = None) -> dict[str, str]:
    env = load_runtime_env(base_env=runtime_env) if runtime_env is not None else load_runtime_env()
    return {key: str(value) for key, value in env.items() if value is not None}


def _has_value(value: str | None) -> bool:
    return bool(value and value.strip())


def check_env_required(keys: Iterable[str], env: Mapping[str, str]) -> dict[str, Any]:
    """Return missing environment keys among ``keys``."""

    missing = sorted(key for key in keys if not _has_value(env.get(key)))
    status = "ok" if not missing else "fail"
    return {"status": status, "missing": missing}


def check_path_exists_writable(path: Path, *, anchor: Path | None = None) -> dict[str, Any]:
    """Validate whether ``path`` exists, is a directory and writable."""

    resolved = path.expanduser().resolve()
    info: dict[str, Any] = {
        "path": str(resolved),
        "exists": resolved.exists(),
        "is_dir": resolved.is_dir(),
        "writable": False,
        "same_filesystem": None,
    }

    if not info["exists"] or not info["is_dir"]:
        return info

    token = f".selfcheck-{uuid4().hex}"
    probe = resolved / token
    try:
        with probe.open("wb") as handle:
            handle.write(b"selfcheck")
            handle.flush()
            os.fsync(handle.fileno())
        info["writable"] = True
    except OSError:
        info["writable"] = False
    finally:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            # Deleting the probe failed; treat as non-writable.
            info["writable"] = False

    if anchor is not None and anchor.exists():
        try:
            info["same_filesystem"] = anchor.stat().st_dev == resolved.stat().st_dev
        except OSError:
            info["same_filesystem"] = False

    return info


def _probe_file_writable(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("ab") as handle:
            handle.write(b"")
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except OSError:
        return False


def _probe_idempotency_sqlite(path: Path) -> tuple[bool, dict[str, Any]]:
    info: dict[str, Any] = {"path": str(path)}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        info["error"] = str(exc)
        info["errno"] = getattr(exc, "errno", None)
        return False, info

    connection: sqlite3.Connection | None = None
    inserted = False
    token = f"ready-{uuid4().hex}"
    try:
        connection = sqlite3.connect(path, timeout=0.25)
        connection.isolation_level = None
        connection.execute(SQLITE_CREATE_TABLE)
        connection.execute("BEGIN IMMEDIATE")
        now = time.time()
        inserted = connection.execute(SQLITE_INSERT, (token, now, now)).rowcount == 1
        connection.execute(SQLITE_DELETE, (token,))
        connection.commit()
        info["inserted"] = inserted
        return True, info
    except sqlite3.Error as exc:
        if connection is not None:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
        info["error"] = str(exc)
        info["type"] = exc.__class__.__name__
        info["inserted"] = inserted
        return False, info
    finally:
        if connection is not None:
            connection.close()


def check_tcp_reachable(
    host: str,
    port: int,
    *,
    retries: int = 3,
    timeout: float = 1.0,
) -> bool:
    """Return whether a TCP endpoint is reachable within ``retries`` attempts."""

    if retries < 1:
        retries = 1
    for attempt in range(1, retries + 1):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError as exc:
            logger.debug(
                "TCP reachability attempt failed",
                exc_info=exc,
                extra={
                    "event": "selfcheck.tcp_retry",
                    "host": host,
                    "port": port,
                    "attempt": attempt,
                    "retries": retries,
                },
            )
            time.sleep(0.05)
    return False


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    text = value.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def aggregate_ready(
    runtime_env: Mapping[str, Any] | None = None,
) -> ReadyReport:
    """Aggregate readiness information covering environment, paths and dependencies."""

    env = _normalise_env(runtime_env)
    checks: dict[str, Any] = {}
    issues: list[ReadyIssue] = []

    base_url_key: str | None = None
    base_url_value: str | None = None
    for candidate in _SLSKD_BASE_URL_KEYS:
        raw_value = env.get(candidate)
        if _has_value(raw_value):
            base_url_key = candidate
            base_url_value = str(raw_value).strip()
            break

    required_env_keys = list(_REQUIRED_ENV_BASE)
    if base_url_key is None:
        required_env_keys.extend(["SLSKD_HOST", "SLSKD_PORT"])

    env_check = check_env_required(required_env_keys, env)
    env_check["soulseekd"] = {
        "mode": "base_url" if base_url_key else "host_port",
        "key": base_url_key,
    }
    checks["env"] = env_check

    missing_keys = set(env_check["missing"])

    api_key_value = env.get("HARMONY_API_KEY") or env.get("HARMONY_API_KEYS")
    if not _has_value(api_key_value):
        missing_keys.add("HARMONY_API_KEY")

    database_required = _parse_bool(env.get("HEALTH_READY_REQUIRE_DB"))
    if database_required is None:
        database_required = True

    if missing_keys:
        env_check["missing"] = sorted(missing_keys)
        env_check["status"] = "fail"
        missing_list = ", ".join(sorted(missing_keys))
        issues.append(
            ReadyIssue(
                component="env",
                message=f"Missing required environment variables: {missing_list}",
                exit_code=EX_CONFIG,
                details={"missing": sorted(missing_keys)},
            )
        )

    oauth: dict[str, Any] = {
        "client_id": _has_value(env.get("SPOTIFY_CLIENT_ID")),
        "client_secret": _has_value(env.get("SPOTIFY_CLIENT_SECRET")),
        "split_mode": None,
    }

    raw_split = env.get("OAUTH_SPLIT_MODE")
    split_mode = _parse_bool(raw_split) if raw_split is not None else None
    if split_mode is None and raw_split is not None:
        issues.append(
            ReadyIssue(
                component="oauth",
                message="OAUTH_SPLIT_MODE must be either true or false",
                exit_code=EX_SOFTWARE,
                details={"value": raw_split},
            )
        )
    oauth["split_mode"] = split_mode
    checks["oauth"] = oauth

    downloads_path = env.get("DOWNLOADS_DIR")
    music_path = env.get("MUSIC_DIR")
    oauth_state_path = env.get("OAUTH_STATE_DIR")

    paths: dict[str, Any] = {}
    if downloads_path:
        downloads_info = check_path_exists_writable(Path(downloads_path))
        paths["downloads"] = downloads_info
        if not (
            downloads_info["exists"] and downloads_info["is_dir"] and downloads_info["writable"]
        ):
            issues.append(
                ReadyIssue(
                    component="paths",
                    message="DOWNLOADS_DIR must exist and be writable",
                    exit_code=EX_OSERR,
                    details=downloads_info,
                )
            )
    if music_path:
        music_info = check_path_exists_writable(Path(music_path))
        paths["music"] = music_info
        if not (music_info["exists"] and music_info["is_dir"] and music_info["writable"]):
            issues.append(
                ReadyIssue(
                    component="paths",
                    message="MUSIC_DIR must exist and be writable",
                    exit_code=EX_OSERR,
                    details=music_info,
                )
            )
    oauth_state_required = bool(split_mode)
    if oauth_state_required:
        if not _has_value(oauth_state_path):
            issues.append(
                ReadyIssue(
                    component="oauth",
                    message="OAUTH_STATE_DIR must be configured when OAUTH_SPLIT_MODE is true",
                    exit_code=EX_CONFIG,
                    details={},
                )
            )
        else:
            downloads_anchor = Path(downloads_path) if downloads_path else None
            oauth_state_info = check_path_exists_writable(
                Path(oauth_state_path), anchor=downloads_anchor
            )
            oauth_state_info["required"] = True
            paths["oauth_state"] = oauth_state_info
            if not (
                oauth_state_info["exists"]
                and oauth_state_info["is_dir"]
                and oauth_state_info["writable"]
            ):
                issues.append(
                    ReadyIssue(
                        component="oauth",
                        message="OAUTH_STATE_DIR must exist and be writable in split mode",
                        exit_code=EX_OSERR,
                        details=oauth_state_info,
                    )
                )
            elif oauth_state_info.get("same_filesystem") is False:
                # The OAuth state directory must share a filesystem with the downloads
                # directory for atomic moves.
                issues.append(
                    ReadyIssue(
                        component="oauth",
                        message=(
                            "OAUTH_STATE_DIR must reside on the same filesystem as DOWNLOADS_DIR"
                        ),
                        exit_code=EX_SOFTWARE,
                        details=oauth_state_info,
                    )
                )
        if "oauth_state" not in paths:
            paths["oauth_state"] = {
                "required": True,
                "path": oauth_state_path or "",
                "exists": False,
                "is_dir": False,
                "writable": False,
                "same_filesystem": None,
            }
    elif oauth_state_path:
        oauth_state_info = check_path_exists_writable(Path(oauth_state_path))
        oauth_state_info["required"] = False
        paths["oauth_state"] = oauth_state_info

    checks["paths"] = paths

    host_value = (env.get("SLSKD_HOST") or "").strip()
    port_value = (env.get("SLSKD_PORT") or "").strip()
    soulseekd: dict[str, Any] = {
        "host": None,
        "port": None,
        "reachable": False,
        "base_url": base_url_value or None,
        "base_url_key": base_url_key,
        "configured_host": host_value or None,
        "configured_port": port_value or None,
        "source": None,
    }

    port: int | None = None
    if port_value:
        try:
            port = int(port_value)
        except ValueError:
            issues.append(
                ReadyIssue(
                    component="soulseekd",
                    message="SLSKD_PORT must be an integer",
                    exit_code=EX_SOFTWARE,
                    details={"value": port_value},
                )
            )

    resolved_host: str | None = None
    resolved_port: int | None = None
    source: str | None = None

    if host_value and port is not None:
        resolved_host = host_value
        resolved_port = port
        source = "host_port"
    else:
        if base_url_value:
            parsed = urlparse(base_url_value)
            parsed_host = parsed.hostname
            parsed_port = parsed.port
            scheme = parsed.scheme.lower()

            if not parsed_host:
                issues.append(
                    ReadyIssue(
                        component="soulseekd",
                        message=f"{base_url_key or 'SLSKD_BASE_URL'} must include a hostname",
                        exit_code=EX_CONFIG,
                        details={"value": base_url_value},
                    )
                )
            else:
                resolved_host = parsed_host

            if parsed_port is not None:
                resolved_port = parsed_port
            else:
                default_port = _DEFAULT_PORT_BY_SCHEME.get(scheme)
                if default_port is not None:
                    resolved_port = default_port
                elif parsed_host is not None:
                    issues.append(
                        ReadyIssue(
                            component="soulseekd",
                            message=(
                                f"{base_url_key or 'SLSKD_BASE_URL'} must include an explicit port"
                            ),
                            exit_code=EX_CONFIG,
                            details={"value": base_url_value},
                        )
                    )

            if resolved_host and resolved_port is not None:
                source = "base_url"

    if resolved_host and resolved_port is not None:
        soulseekd["host"] = resolved_host
        soulseekd["port"] = resolved_port
        soulseekd["source"] = source
        reachable = check_tcp_reachable(resolved_host, resolved_port)
        soulseekd["reachable"] = reachable
        if not reachable:
            issues.append(
                ReadyIssue(
                    component="soulseekd",
                    message=f"Unable to reach Soulseekd at {resolved_host}:{resolved_port}",
                    exit_code=EX_UNAVAILABLE,
                    details={"host": resolved_host, "port": resolved_port},
                )
            )
    else:
        issues.append(
            ReadyIssue(
                component="soulseekd",
                message="Soulseekd base URL or host/port must be configured",
                exit_code=EX_CONFIG,
                details={
                    "base_url_key": base_url_key,
                    "base_url": base_url_value,
                    "host": host_value or None,
                    "port": port_value or None,
                },
            )
        )
    checks["soulseekd"] = soulseekd

    profile = _resolve_profile(env)
    configured_url = env.get("DATABASE_URL")
    database_url = configured_url if _has_value(configured_url) else _default_database_url(profile)

    database: dict[str, Any] = {
        "required": database_required,
        "configured": bool(_has_value(configured_url)),
        "mode": None,
        "path": None,
        "exists": None,
        "writable": None,
        "using_default": not _has_value(configured_url),
    }

    try:
        url = make_url(database_url)
    except ArgumentError:
        database["error"] = "invalid_url"
        issues.append(
            ReadyIssue(
                component="database",
                message="DATABASE_URL is not a valid sqlite+ SQLAlchemy URL",
                exit_code=EX_CONFIG,
                details={"url": database_url},
            )
        )
    else:
        driver = url.drivername.lower()
        database["driver"] = driver
        if not driver.startswith("sqlite"):
            issues.append(
                ReadyIssue(
                    component="database",
                    message="DATABASE_URL must use a sqlite+ driver",
                    exit_code=EX_CONFIG,
                    details={"driver": driver, "url": database_url},
                )
            )
        else:
            database["mode"] = "memory"
            database["exists"] = True
            database["writable"] = True
            database_path: Path | None = None
            if url.database and url.database not in {":memory:"}:
                database_path = Path(url.database)
                if not database_path.is_absolute():
                    database_path = (Path.cwd() / database_path).resolve()
                database["mode"] = "file"
                database["path"] = str(database_path)
                exists = database_path.exists()
                database["exists"] = exists
                parent_info = check_path_exists_writable(database_path.parent)
                database["parent"] = parent_info
                if exists:
                    writable = _probe_file_writable(database_path)
                    database["writable"] = writable
                    if database_required and not writable:
                        issues.append(
                            ReadyIssue(
                                component="database",
                                message="Database file is not writable",
                                exit_code=EX_OSERR,
                                details={"path": str(database_path)},
                            )
                        )
                else:
                    database["writable"] = False
                    if database_required:
                        issues.append(
                            ReadyIssue(
                                component="database",
                                message="Database file does not exist",
                                exit_code=EX_OSERR,
                                details={"path": str(database_path)},
                            )
                        )
    checks["database"] = database

    idempotency: dict[str, Any] = {}
    try:
        hdm_config = HdmConfig.from_env(env)
    except ValueError as exc:
        idempotency.update(
            {
                "status": "fail",
                "error": str(exc),
                "backend": str(env.get("IDEMPOTENCY_BACKEND")),
            }
        )
        issues.append(
            ReadyIssue(
                component="idempotency",
                message="Invalid idempotency configuration",
                exit_code=EX_CONFIG,
                details=dict(idempotency),
            )
        )
    else:
        backend = hdm_config.idempotency_backend
        idempotency["backend"] = backend
        if backend == "sqlite":
            sqlite_path = Path(hdm_config.idempotency_sqlite_path).expanduser()
            success, details = _probe_idempotency_sqlite(sqlite_path)
            idempotency.update(details)
            idempotency["status"] = "ok" if success else "fail"
            if not success:
                issues.append(
                    ReadyIssue(
                        component="idempotency",
                        message="SQLite idempotency probe failed",
                        exit_code=EX_UNAVAILABLE,
                        details=dict(idempotency),
                    )
                )
        else:
            idempotency["status"] = "ok"
            idempotency["mode"] = "memory"
    checks["idempotency"] = idempotency

    status = "ok" if not issues else "fail"
    return ReadyReport(status=status, checks=checks, issues=issues)


def run_startup_guards(
    runtime_env: Mapping[str, Any] | None = None,
) -> None:
    """Execute startup guards and exit the interpreter when they fail."""

    report = aggregate_ready(runtime_env=runtime_env)

    env_source: Mapping[str, Any]
    if runtime_env is not None:
        env_source = runtime_env
    else:
        env_source = os.environ
    optional_env_snapshot = {key: env_source.get(key) for key in _OPTIONAL_ENV_KEYS}

    paths = report.checks.get("paths", {})
    oauth = report.checks.get("oauth", {})
    soulseekd = report.checks.get("soulseekd", {})
    database = report.checks.get("database", {})
    idempotency = report.checks.get("idempotency", {})

    logger.info(
        "Startup environment summary",
        extra={
            "event": "startup.environment",
            "downloads_dir": paths.get("downloads", {}).get("path"),
            "music_dir": paths.get("music", {}).get("path"),
            "oauth_split_mode": oauth.get("split_mode"),
            "oauth_state_dir": paths.get("oauth_state", {}).get("path"),
            "soulseekd_host": soulseekd.get("host"),
            "soulseekd_port": soulseekd.get("port"),
            "database_required": database.get("required"),
            "database_mode": database.get("mode"),
            "database_path": database.get("path"),
            "database_using_default": database.get("using_default"),
            "idempotency_backend": idempotency.get("backend"),
            "idempotency_status": idempotency.get("status"),
            "idempotency_path": idempotency.get("path"),
            "umask": optional_env_snapshot.get("UMASK"),
            "puid": optional_env_snapshot.get("PUID"),
            "pgid": optional_env_snapshot.get("PGID"),
        },
    )

    if report.ok:
        logger.info("Startup guards passed", extra={"event": "startup.ready"})
        return

    issue = report.issues[0]
    logger.error(
        "Startup guard failure: %s",
        issue.message,
        extra={
            "event": "startup.failed",
            "component": issue.component,
            "details": dict(issue.details),
            "exit_code": issue.exit_code,
        },
    )
    raise SystemExit(issue.exit_code)


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harmony operational self-checks")
    parser.add_argument(
        "--assert-startup",
        action="store_true",
        help="Exit with a non-zero code when startup guards fail",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print verbose readiness payload",
    )
    args = parser.parse_args(argv)

    if args.assert_startup:
        run_startup_guards()
        return 0

    report = aggregate_ready()
    payload = report.to_dict(verbose=args.verbose or not report.ok)
    print(json.dumps(payload, indent=2 if args.verbose else None, sort_keys=args.verbose))
    return 0 if report.ok else 1


def main() -> None:
    raise SystemExit(_cli())


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
