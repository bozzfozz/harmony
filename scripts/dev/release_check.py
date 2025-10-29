"""Structured release gate runner for the Harmony "release-check" workflow."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import json
import os
import shlex
import subprocess
import sys
import time

DEFAULT_TARGETS: tuple[str, ...] = (
    "all",
    "docs-verify",
    "pip-audit",
    "ui-smoke",
)

COMMAND_OVERRIDE_ENV = "RELEASE_CHECK_COMMANDS"


@dataclass(frozen=True)
class ReleaseCheckStep:
    """Single step of the release workflow."""

    label: str
    command: Sequence[str]


class ReleaseCheckError(RuntimeError):
    """Raised when a release-check step fails."""

    def __init__(self, step: ReleaseCheckStep, exit_code: int) -> None:
        super().__init__(f"Step '{step.label}' failed with exit code {exit_code}")
        self.step = step
        self.exit_code = exit_code


def _utc_now() -> str:
    return datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _log_event(
    stream, *, event: str, step: ReleaseCheckStep | None, status: str, **extra: object
) -> None:
    record = {
        "timestamp": _utc_now(),
        "event": event,
        "status": status,
    }
    if step is not None:
        record["step"] = step.label
    if extra:
        record.update(extra)
    stream.write(json.dumps(record) + "\n")
    stream.flush()


def _build_default_steps(make_command: str) -> list[ReleaseCheckStep]:
    steps: list[ReleaseCheckStep] = []
    for target in DEFAULT_TARGETS:
        label = f"{make_command} {target}"
        steps.append(ReleaseCheckStep(label=label, command=[make_command, target]))
    return steps


def _load_steps(env: Mapping[str, str], make_command: str) -> list[ReleaseCheckStep]:
    override = env.get(COMMAND_OVERRIDE_ENV)
    if not override:
        return _build_default_steps(make_command)

    commands: list[str] = [line.strip() for line in override.splitlines() if line.strip()]
    if not commands:
        raise ValueError(f"Environment variable {COMMAND_OVERRIDE_ENV} did not define any commands")

    steps: list[ReleaseCheckStep] = []
    for command in commands:
        parts = shlex.split(command)
        if not parts:
            raise ValueError(f"Configured command '{command}' resolved to an empty argument list")
        steps.append(ReleaseCheckStep(label=command, command=tuple(parts)))
    return steps


def _run_step(step: ReleaseCheckStep) -> int:
    proc = subprocess.run(step.command, check=False)
    return proc.returncode


def run_release_check(
    *,
    dry_run: bool,
    env: Mapping[str, str] | None = None,
    stream=None,
    make_command: str | None = None,
) -> None:
    """Execute the release-check workflow."""

    if env is None:
        env = os.environ  # pragma: no cover - exercised indirectly
    if stream is None:
        stream = sys.stdout
    make = make_command or env.get("MAKE", "make")

    steps = _load_steps(env, make)
    _log_event(stream, event="workflow", step=None, status="starting", steps=len(steps))

    try:
        for step in steps:
            _log_event(stream, event="step", step=step, status="starting")
            start = time.perf_counter()

            if dry_run:
                _log_event(
                    stream,
                    event="step",
                    step=step,
                    status="skipped",
                    duration_seconds=0.0,
                )
                continue

            exit_code = _run_step(step)
            duration = time.perf_counter() - start

            if exit_code != 0:
                _log_event(
                    stream,
                    event="step",
                    step=step,
                    status="failed",
                    exit_code=exit_code,
                    duration_seconds=round(duration, 6),
                )
                raise ReleaseCheckError(step, exit_code)

            _log_event(
                stream,
                event="step",
                step=step,
                status="succeeded",
                duration_seconds=round(duration, 6),
            )
    except ReleaseCheckError as exc:
        _log_event(
            stream,
            event="workflow",
            step=None,
            status="failed",
            failed_step=exc.step.label,
            exit_code=exc.exit_code,
        )
        raise

    _log_event(stream, event="workflow", step=None, status="completed")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Harmony release gate.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned steps without executing them.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        run_release_check(dry_run=args.dry_run)
    except ReleaseCheckError as exc:
        return exc.exit_code
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive guardrail
        print(f"release-check failed with unexpected error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
