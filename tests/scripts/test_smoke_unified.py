from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

SCRIPT_PATH = Path("scripts/dev/smoke_unified.sh").resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]


def _run_smoke(**env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.mark.parametrize("value", ["0", "false", "False", "OFF", " disabled "])
def test_smoke_unified_skips_when_disabled(value: str) -> None:
    result = _run_smoke(SMOKE_ENABLED=value)

    assert result.returncode == 0
    assert "Smoke checks disabled" in result.stderr
    # Script should exit before touching stdout in the disabled case.
    assert result.stdout == ""
