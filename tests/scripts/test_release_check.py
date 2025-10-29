from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path("scripts/dev/release_check.py")


def _run_release_check(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT_PATH), *args]
    return subprocess.run(command, capture_output=True, text=True, env=env)


def _parse_logs(output: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_dry_run_emits_plan_without_execution() -> None:
    result = _run_release_check("--dry-run")

    assert result.returncode == 0
    logs = _parse_logs(result.stdout)

    skipped = [entry for entry in logs if entry["event"] == "step" and entry["status"] == "skipped"]

    assert len(skipped) == 4
    assert logs[-1]["event"] == "workflow"
    assert logs[-1]["status"] == "completed"


def test_successful_execution_runs_all_commands() -> None:
    success_script = shlex.join([sys.executable, "-c", "import sys"])
    env = dict(os.environ)
    env["RELEASE_CHECK_COMMANDS"] = "\n".join([success_script, success_script])

    result = _run_release_check(env=env)

    assert result.returncode == 0

    logs = _parse_logs(result.stdout)
    succeeded = [
        entry for entry in logs if entry["event"] == "step" and entry["status"] == "succeeded"
    ]

    assert len(succeeded) == 2
    assert logs[-1]["event"] == "workflow"
    assert logs[-1]["status"] == "completed"


def test_failure_stops_pipeline_and_returns_exit_code() -> None:
    success_script = shlex.join([sys.executable, "-c", "import sys"])
    failing_script = shlex.join([sys.executable, "-c", "import sys; sys.exit(5)"])

    env = dict(os.environ)
    env["RELEASE_CHECK_COMMANDS"] = "\n".join([failing_script, success_script])

    result = _run_release_check(env=env)

    assert result.returncode == 5

    logs = _parse_logs(result.stdout)
    step_logs = [entry for entry in logs if entry["event"] == "step"]

    assert step_logs[-1]["status"] == "failed"
    assert step_logs[-1]["step"] == failing_script

    workflow_logs = [entry for entry in logs if entry["event"] == "workflow"]
    assert workflow_logs[-1]["status"] == "failed"
    assert workflow_logs[-1]["exit_code"] == 5
    assert workflow_logs[-1]["failed_step"] == failing_script

    started_steps = [entry["step"] for entry in step_logs if entry["status"] == "starting"]
    assert started_steps == [failing_script]
