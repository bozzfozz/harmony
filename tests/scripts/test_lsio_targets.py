import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "dev" / "smoke_lsio.sh"


def run_make_dry(target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "-n", target],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def test_make_image_lsio_target_command():
    result = run_make_dry("image-lsio")
    expected = "docker build -f docker/Dockerfile.lsio -t lscr.io/linuxserver/harmony:latest ."
    assert expected in result.stdout


def test_make_smoke_lsio_target_invokes_script():
    result = run_make_dry("smoke-lsio")
    assert "./scripts/dev/smoke_lsio.sh" in result.stdout


@pytest.mark.parametrize(
    "env, expected_code",
    [
        ({"HARMONY_LSIO_SMOKE_DRY_RUN": "1"}, 0),
        ({"HARMONY_LSIO_SMOKE_FORCE_FAIL": "1"}, 1),
    ],
)
def test_smoke_lsio_script_modes(env: dict[str, str], expected_code: int):
    process_env = os.environ.copy()
    process_env.update(env)
    completed = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=process_env,
    )
    assert completed.returncode == expected_code, completed.stderr
    if expected_code == 0:
        assert "Dry run requested" in completed.stderr
    else:
        assert "Forced failure" in completed.stderr
