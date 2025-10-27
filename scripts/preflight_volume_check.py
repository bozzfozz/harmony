"""Preflight checks for Harmony's Docker volume directories.

The LinuxServer.io container exposes three writable mounts – ``/config``,
``/downloads`` and ``/music``. This utility ensures that their corresponding
host directories exist, are writable for the configured container user, and
optionally adjusts ownership when executed with elevated privileges.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
import os
from pathlib import Path
import stat
import sys
import uuid


class PreflightError(RuntimeError):
    """Raised when filesystem preflight checks cannot be satisfied."""


def _is_root() -> bool:
    """Return ``True`` when the current process runs with root privileges."""

    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        # Windows compatibility – fall back to assuming non-root execution.
        return False
    return geteuid() == 0


def _apply_ownership(path: Path, puid: int, pgid: int) -> None:
    """Set ownership if running as root, otherwise leave untouched."""

    if not _is_root():
        return
    try:
        os.chown(path, puid, pgid)
    except PermissionError as exc:
        raise PreflightError(f"Unable to adjust ownership for {path!s}: {exc}.") from exc


def _check_writable(path: Path, puid: int, pgid: int) -> bool:
    """Determine whether the requested uid/gid can write to *path*."""

    metadata = path.stat()
    mode = metadata.st_mode
    if metadata.st_uid == puid and mode & stat.S_IWUSR:
        return True
    if metadata.st_gid == pgid and mode & stat.S_IWGRP:
        return True
    if mode & stat.S_IWOTH:
        return True
    return False


def _probe_write(path: Path) -> None:
    """Create and remove a temporary file to verify write access."""

    probe = path / f".harmony-preflight-{uuid.uuid4().hex}"
    try:
        probe.write_text("ok", encoding="utf-8")
    except OSError as exc:  # pragma: no cover - error path tested separately
        raise PreflightError(f"Unable to write to {path!s}: {exc}.") from exc
    try:
        probe.unlink()
    except OSError as exc:  # pragma: no cover - extremely unlikely
        raise PreflightError(
            f"Created probe file {probe!s} but failed to clean it up: {exc}."
        ) from exc


def _ensure_directory(path: Path, label: str, puid: int, pgid: int) -> None:
    """Create *path* (including parents) and validate permissions."""

    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PreflightError(f"Unable to create {label} directory at {path!s}: {exc}.") from exc
    _apply_ownership(path, puid, pgid)
    if not _check_writable(path, puid, pgid):
        raise PreflightError(
            "Directory permissions reject container user writes. "
            f"Fix with: sudo chown {puid}:{pgid} {path!s}"
        )
    _probe_write(path)


def ensure_directories(
    *,
    config_dir: Path,
    downloads_dir: Path,
    music_dir: Path,
    puid: int,
    pgid: int,
) -> None:
    """Create and validate all volume directories."""

    ordered: Iterable[tuple[str, Path]] = (
        ("config", config_dir),
        ("downloads", downloads_dir),
        ("music", music_dir),
    )
    for label, path in ordered:
        _ensure_directory(path.resolve(), label, puid, pgid)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create /config, /downloads and /music host directories for the "
            "Harmony container and verify they are writable for the configured "
            "container user."
        )
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path("volumes/config"),
        help="Host directory mapped to /config inside the container.",
    )
    parser.add_argument(
        "--downloads-dir",
        type=Path,
        default=Path("volumes/downloads"),
        help="Host directory mapped to /downloads inside the container.",
    )
    parser.add_argument(
        "--music-dir",
        type=Path,
        default=Path("volumes/music"),
        help="Host directory mapped to /music inside the container.",
    )
    parser.add_argument(
        "--puid",
        type=int,
        default=int(os.environ.get("PUID", "1000")),
        help="Container user ID (PUID). Defaults to the PUID environment variable or 1000.",
    )
    parser.add_argument(
        "--pgid",
        type=int,
        default=int(os.environ.get("PGID", "1000")),
        help="Container group ID (PGID). Defaults to the PGID environment variable or 1000.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    downloads_dir = args.downloads_dir
    music_dir = args.music_dir
    try:
        ensure_directories(
            config_dir=args.config_dir,
            downloads_dir=downloads_dir,
            music_dir=music_dir,
            puid=args.puid,
            pgid=args.pgid,
        )
    except PreflightError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(
        "[ok] Prepared LinuxServer.io volume directories:\n"
        f"  /config     ← {args.config_dir.resolve()}\n"
        f"  /downloads ← {downloads_dir.resolve()}\n"
        f"  /music     ← {music_dir.resolve()}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
