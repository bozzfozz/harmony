#!/usr/bin/env python3
"""Run the same workflow as ``make all`` without requiring GNU Make."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Protocol, cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEV_SCRIPTS = PROJECT_ROOT / "scripts" / "dev"
DEFAULT_RUNNER = cast("Runner", subprocess.run)


class Runner(Protocol):
    """Protocol describing how subprocess runners behave."""

    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None,
        check: bool,
    ) -> subprocess.CompletedProcess[str] | None:
        """Execute ``command`` within ``cwd`` and optionally ``env``."""


@dataclass(frozen=True, slots=True)
class PipelineStep:
    """Description of a single command within the make-all pipeline."""

    name: str
    command: tuple[str, ...]


DEFAULT_STEPS: tuple[PipelineStep, ...] = (
    PipelineStep(name="fmt", command=(str(DEV_SCRIPTS / "fmt.sh"),)),
    PipelineStep(name="lint", command=(str(DEV_SCRIPTS / "lint_py.sh"),)),
    PipelineStep(name="dep-sync", command=(str(DEV_SCRIPTS / "dep_sync_py.sh"),)),
    PipelineStep(name="supply-guard", command=(str(DEV_SCRIPTS / "supply_guard.sh"),)),
    PipelineStep(name="smoke", command=(str(DEV_SCRIPTS / "smoke_unified.sh"),)),
)


def _log(action: str, status: str, **metadata: object) -> None:
    """Emit a structured log line for observability."""

    payload: dict[str, object] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "agent": "make-all",  # keep short for log readability
        "action": action,
        "status": status,
    }
    payload.update(metadata)
    print(json.dumps(payload, sort_keys=True), flush=True)


def _merge_env(overrides: Mapping[str, str] | None) -> dict[str, str]:
    """Combine process environment with optional overrides."""

    merged = dict(os.environ)
    if overrides:
        merged.update(overrides)
    return merged


def run_step(
    step: PipelineStep,
    *,
    runner: Runner = DEFAULT_RUNNER,
    cwd: Path = PROJECT_ROOT,
    env: Mapping[str, str] | None = None,
    index: int,
) -> None:
    """Execute a single pipeline step and log its lifecycle."""

    command_list = list(step.command)
    _log("command", "pending", stage=step.name, step=index, command=command_list)
    try:
        runner(step.command, cwd=cwd, env=env, check=True)
    except subprocess.CalledProcessError as error:
        _log(
            "command",
            "error",
            stage=step.name,
            step=index,
            returncode=error.returncode,
            command=command_list,
        )
        raise
    except Exception as error:  # pragma: no cover - defensive logging
        _log(
            "command",
            "error",
            stage=step.name,
            step=index,
            error=error.__class__.__name__,
            message=str(error),
            command=command_list,
        )
        raise
    else:
        _log("command", "success", stage=step.name, step=index)


def run_pipeline(
    steps: Iterable[PipelineStep] | None = None,
    *,
    runner: Runner = DEFAULT_RUNNER,
    cwd: Path = PROJECT_ROOT,
    env_overrides: Mapping[str, str] | None = None,
) -> None:
    """Execute each pipeline step sequentially."""

    sequence = tuple(steps or DEFAULT_STEPS)
    runtime_env = _merge_env(env_overrides)

    for index, step in enumerate(sequence, start=1):
        try:
            run_step(step, runner=runner, cwd=cwd, env=runtime_env, index=index)
        except Exception:
            _log("pipeline", "error", stage=step.name, step=index)
            raise
        else:
            _log("pipeline", "progress", stage=step.name, step=index)

    _log("pipeline", "success", steps=len(sequence))


def main() -> int:
    """Entry-point for CLI usage."""

    run_pipeline()
    return 0


if __name__ == "__main__":
    sys.exit(main())
