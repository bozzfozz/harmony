#!/usr/bin/env python3
"""Validate packaging commands for release automation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
import importlib.util
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]

COMMAND_SEQUENCE: tuple[tuple[str, ...], ...] = (
    (sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", "."),
    (sys.executable, "-m", "pip", "wheel", ".", "-w", "dist/"),
    (sys.executable, "-m", "build"),
)

BUILD_INSTALL_COMMAND: tuple[str, ...] = (
    sys.executable,
    "-m",
    "pip",
    "install",
    "build",
)


def _log(action: str, status: str, **metadata: object) -> None:
    """Emit a structured log line for observability."""

    payload: dict[str, object] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "agent": "package-verify",
        "action": action,
        "status": status,
    }
    payload.update(metadata)
    print(json.dumps(payload, sort_keys=True), flush=True)


def clean_artifacts(root: Path) -> None:
    """Remove build artefacts to guarantee reproducible packaging runs."""

    for directory in ("build", "dist"):
        target = root / directory
        if target.exists():
            _log("clean", "pending", path=str(target))
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            _log("clean", "success", path=str(target))

    for egg_info in root.glob("*.egg-info"):
        if egg_info.exists():
            _log("clean", "pending", path=str(egg_info))
            if egg_info.is_dir():
                shutil.rmtree(egg_info)
            else:
                egg_info.unlink()
            _log("clean", "success", path=str(egg_info))


def run_command(command: Sequence[str], root: Path) -> None:
    """Execute a packaging command from the project root."""

    _log("command", "pending", command=list(command))
    subprocess.run(command, cwd=root, check=True)
    _log("command", "success", command=list(command))


def ensure_build_tool(
    root: Path,
    runner: Callable[[Sequence[str], Path], None] = run_command,
    finder: Callable[[str], object | None] = importlib.util.find_spec,
) -> None:
    """Install the build frontend when it is not available."""

    spec = finder("build")
    if spec is not None and getattr(spec, "loader", None) is not None:
        _log("dependency", "skipped", name="build")
        return

    reason = "not_found" if spec is None else "missing_loader"

    _log("dependency", "pending", name="build", reason=reason)
    try:
        runner(BUILD_INSTALL_COMMAND, root)
    except Exception:  # pragma: no cover - log and re-raise for observability
        _log("dependency", "error", name="build")
        raise
    _log("dependency", "success", name="build")


def run_pipeline(
    root: Path,
    commands: Iterable[Sequence[str]] | None = None,
    runner: Callable[[Sequence[str], Path], None] = run_command,
    ensure_build: bool = True,
) -> None:
    """Execute the packaging pipeline with cleanup between steps."""

    if ensure_build:
        ensure_build_tool(root, runner=runner)

    sequence: Iterable[Sequence[str]] = commands or COMMAND_SEQUENCE
    for index, command in enumerate(sequence):
        clean_artifacts(root)
        runner(command, root)
        _log("pipeline", "progress", step=index + 1)


def main() -> int:
    """Entry point for CLI usage."""

    run_pipeline(PROJECT_ROOT)
    _log("pipeline", "success", steps=len(COMMAND_SEQUENCE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
