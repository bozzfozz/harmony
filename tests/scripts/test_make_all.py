from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

from scripts.dev import make_all


class StubRunner:
    """Collect invocations for assertions within tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path,
        env: Mapping[str, str] | None,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(
            {
                "command": command,
                "cwd": cwd,
                "env": dict(env or {}),
                "check": check,
            }
        )
        return subprocess.CompletedProcess(command, 0)


def _parse_logs(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_run_pipeline_success_logs_progress(capsys: pytest.CaptureFixture[str]) -> None:
    steps = (
        make_all.PipelineStep(name="alpha", command=("cmd1",)),
        make_all.PipelineStep(name="beta", command=("cmd2",)),
    )
    runner = StubRunner()

    overrides = {"VAR": "1"}
    make_all.run_pipeline(
        steps=steps,
        runner=runner,
        cwd=Path("/tmp/project"),
        env_overrides=overrides,
    )

    captured = capsys.readouterr().out
    logs = _parse_logs(captured)

    expected_env = dict(os.environ)
    expected_env.update(overrides)

    assert runner.calls == [
        {
            "command": ("cmd1",),
            "cwd": Path("/tmp/project"),
            "env": expected_env,
            "check": True,
        },
        {
            "command": ("cmd2",),
            "cwd": Path("/tmp/project"),
            "env": expected_env,
            "check": True,
        },
    ]

    statuses = [entry["status"] for entry in logs if entry["action"] == "pipeline"]
    assert statuses.count("progress") == 2
    assert statuses[-1] == "success"


def test_run_pipeline_failure_logs_error(capsys: pytest.CaptureFixture[str]) -> None:
    steps = (make_all.PipelineStep(name="omega", command=("boom",)),)

    def failing_runner(
        command: tuple[str, ...],
        *,
        cwd: Path,
        env: Mapping[str, str] | None,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(returncode=9, cmd=command)

    with pytest.raises(subprocess.CalledProcessError):
        make_all.run_pipeline(
            steps=steps,
            runner=failing_runner,
            cwd=Path("/tmp/project"),
            env_overrides=None,
        )

    logs = _parse_logs(capsys.readouterr().out)
    assert logs[-1]["status"] == "error"
    assert logs[-1]["action"] == "pipeline"
    assert logs[-1]["stage"] == "omega"
