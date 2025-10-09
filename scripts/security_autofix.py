#!/usr/bin/env python3
"""Run `pip-audit` with optional autofix for Harmony dependency manifests."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REQUIREMENTS = (
    REPO_ROOT / "requirements.txt",
    REPO_ROOT / "requirements-dev.txt",
)


@dataclass(frozen=True)
class AuditTask:
    """Describe a `pip-audit` invocation."""

    requirement_file: Path
    extra_args: tuple[str, ...] = ()

    def build_command(self, pip_audit_executable: str) -> list[str]:
        command = [pip_audit_executable, "--requirement", str(self.requirement_file)]
        command.extend(self.extra_args)
        return command


@dataclass(frozen=True)
class AuditResult:
    task: AuditTask
    returncode: int


class SecurityAutofixError(RuntimeError):
    """Raised when the security autofix routine encounters a fatal error."""


def log_event(event: str, **fields: object) -> None:
    """Emit structured JSON logs to stdout."""

    payload = {"event": event, **fields}
    logging.info(json.dumps(payload, sort_keys=True))


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "requirements",
        metavar="FILE",
        nargs="*",
        help="Requirement files to audit (defaults to project manifests).",
    )
    parser.add_argument(
        "--pip-audit",
        default="pip-audit",
        help="Executable used to invoke pip-audit (default: %(default)s).",
    )
    parser.add_argument(
        "--no-fix",
        action="store_true",
        help="Run audits without applying fixes (equivalent to omitting --fix).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run pip-audit with --dry-run; implies autofix behaviour without modifying files."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging for debugging the autofix routine.",
    )
    return parser.parse_args(argv)


def resolve_requirement_files(raw_paths: Iterable[str]) -> tuple[Path, ...]:
    if not raw_paths:
        return DEFAULT_REQUIREMENTS

    resolved: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPO_ROOT / raw_path
        resolved.append(path)

    return tuple(resolved)


def build_tasks(
    requirement_files: Iterable[Path], *, apply_fix: bool, dry_run: bool
) -> tuple[AuditTask, ...]:
    tasks: list[AuditTask] = []
    base_args: list[str] = []
    if dry_run:
        base_args.append("--dry-run")
    elif apply_fix:
        base_args.append("--fix")

    for requirement_file in requirement_files:
        tasks.append(
            AuditTask(requirement_file=requirement_file, extra_args=tuple(base_args))
        )
    return tuple(tasks)


def run_task(task: AuditTask, *, pip_audit_executable: str) -> AuditResult:
    if not task.requirement_file.exists():
        raise SecurityAutofixError(
            f"Requirement file missing: {task.requirement_file}"  # pragma: no cover - guard rail
        )

    command = task.build_command(pip_audit_executable)
    log_event("pip_audit.start", command=command)
    try:
        completed = subprocess.run(command, check=False)
    except FileNotFoundError as exc:  # pragma: no cover - depends on environment
        raise SecurityAutofixError(
            f"Unable to execute {pip_audit_executable!r}: {exc}"  # pragma: no cover - guard rail
        ) from exc

    log_event("pip_audit.finish", command=command, returncode=completed.returncode)
    return AuditResult(task=task, returncode=completed.returncode)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    requirement_files = resolve_requirement_files(args.requirements)
    for requirement_file in requirement_files:
        if not requirement_file.exists():
            raise SecurityAutofixError(
                f"Requirement file not found: {requirement_file}"
            )

    tasks = build_tasks(
        requirement_files,
        apply_fix=not args.no_fix,
        dry_run=args.dry_run,
    )

    results: list[AuditResult] = []
    for task in tasks:
        result = run_task(task, pip_audit_executable=args.pip_audit)
        results.append(result)

    failing = [result for result in results if result.returncode != 0]
    if failing:
        failing_paths = [str(result.task.requirement_file) for result in failing]
        log_event("pip_audit.error", failing_files=failing_paths)
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SecurityAutofixError as error:
        log_event("security_autofix.error", message=str(error))
        sys.exit(2)
