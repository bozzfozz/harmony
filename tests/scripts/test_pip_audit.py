"""Tests for the pip-audit bootstrap script."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "pip_audit.sh"


@pytest.fixture()
def _isolated_env(tmp_path: Path) -> dict[str, str]:
    """Return an isolated environment with stubbed uv and pip-audit."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["PIP_AUDIT_STUB_LOG"] = str(tmp_path / "pip_audit.log")
    env["UV_STUB_EXPORT_LOG"] = str(tmp_path / "uv_export.log")

    uv_stub = bin_dir / "uv"
    uv_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "log=${UV_STUB_EXPORT_LOG:-}\n"
        "case \"${1-}\" in\n"
        "  lock)\n"
        "    if [[ ${2-} == --check ]]; then\n"
        "      [[ -n $log ]] && echo \"lock --check\" >>\"$log\"\n"
        "      exit 0\n"
        "    fi\n"
        "    ;;\n"
        "  export)\n"
        "    shift\n"
        "    output=\"\"\n"
        "    while [[ $# -gt 0 ]]; do\n"
        "      case $1 in\n"
        "        --output-file)\n"
        "          output=$2\n"
        "          shift 2\n"
        "          ;;\n"
        "        *)\n"
        "          shift\n"
        "          ;;\n"
        "      esac\n"
        "    done\n"
        "    if [[ -n $output ]]; then\n"
        "      cat >\"$output\" <<'EOF'\n"
        "demo==1.0.0\n"
        "EOF\n"
        "    fi\n"
        "    [[ -n $log ]] && echo \"export $output\" >>\"$log\"\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n"
        "echo \"uv stub unsupported: $*\" >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    uv_stub.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    pip_audit_stub = bin_dir / "pip-audit"
    pip_audit_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "log=${PIP_AUDIT_STUB_LOG}\n"
        "echo \"$*\" >>\"$log\"\n"
        "if [[ -n ${PIP_AUDIT_FAIL:-} ]]; then\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    pip_audit_stub.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    env["PIP_AUDIT_CMD"] = str(pip_audit_stub)
    return env


def test_invokes_configured_pip_audit_command(_isolated_env: dict[str, str]) -> None:
    env = _isolated_env

    result = subprocess.run(
        [str(_SCRIPT_PATH)],
        cwd=_SCRIPT_PATH.parent.parent.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    stub_log = Path(env["PIP_AUDIT_STUB_LOG"]).read_text(encoding="utf-8").splitlines()
    assert stub_log, "expected the pip-audit stub to run"
    assert any("--strict" in line for line in stub_log)
    assert any(line.count("-r") >= 1 for line in stub_log)


def test_reports_failure_when_pip_audit_exits_nonzero(_isolated_env: dict[str, str]) -> None:
    env = _isolated_env
    env["PIP_AUDIT_FAIL"] = "1"

    result = subprocess.run(
        [str(_SCRIPT_PATH)],
        cwd=_SCRIPT_PATH.parent.parent.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "pip-audit detected vulnerabilities" in result.stderr
