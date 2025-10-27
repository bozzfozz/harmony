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
    """Return an isolated environment for invoking the script."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["PIP_AUDIT_BOOTSTRAP_LOG"] = str(tmp_path / "bootstrap.log")
    env["PIP_AUDIT_STUB_LOG"] = str(tmp_path / "pip_audit.log")
    env["PIP_AUDIT_STUB_DIR"] = str(bin_dir)
    return env


def _write_bootstrap_stub(env: dict[str, str]) -> Path:
    """Create a bootstrap helper that installs a pip-audit stub."""

    bin_dir = Path(env["PIP_AUDIT_STUB_DIR"])
    bootstrap_log = Path(env["PIP_AUDIT_BOOTSTRAP_LOG"])
    stub_log = Path(env["PIP_AUDIT_STUB_LOG"])
    stub_path = bin_dir / "pip-audit"

    stub_contents = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'log_file="{stub_log}"\n'
        'if [[ "${1-}" == "--help" ]]; then\n'
        "    printf 'usage: pip-audit\\n  --progress-spinner\\n'\n"
        '    echo "--help" >> "$log_file"\n'
        "    exit 0\n"
        "fi\n"
        'echo "$*" >> "$log_file"\n'
        "printf 'stub audit run %s\\n' \"$*\"\n"
        "exit 0\n"
    )

    bootstrap_contents = (
        "#!/usr/bin/env python3\n"
        "import pathlib\n"
        f"stub_path = pathlib.Path({str(stub_path)!r})\n"
        f'stub_path.write_text({stub_contents!r}, encoding="utf-8")\n'
        "stub_path.chmod(0o755)\n"
        f"log_path = pathlib.Path({str(bootstrap_log)!r})\n"
        'with log_path.open("a", encoding="utf-8") as fh:\n'
        '    fh.write("bootstrap\\n")\n'
    )

    bootstrap_path = bin_dir.parent / "bootstrap.py"
    bootstrap_path.write_text(bootstrap_contents, encoding="utf-8")
    bootstrap_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return bootstrap_path


def test_bootstrap_installs_stub_when_missing(_isolated_env: dict[str, str]) -> None:
    env = _isolated_env
    bootstrap_path = _write_bootstrap_stub(env)
    env["PIP_AUDIT_BOOTSTRAP"] = str(bootstrap_path)

    result = subprocess.run(
        [str(_SCRIPT_PATH)],
        cwd=_SCRIPT_PATH.parent.parent.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "pip-audit installed successfully" in result.stderr

    bootstrap_log = Path(env["PIP_AUDIT_BOOTSTRAP_LOG"]).read_text(encoding="utf-8")
    assert "bootstrap" in bootstrap_log

    stub_log = Path(env["PIP_AUDIT_STUB_LOG"]).read_text(encoding="utf-8").splitlines()
    assert "--help" in stub_log[0]
    assert any("requirements.txt" in line for line in stub_log)


def test_bootstrap_failure_reports_error(_isolated_env: dict[str, str]) -> None:
    env = _isolated_env
    failing_bootstrap = Path(env["PIP_AUDIT_STUB_DIR"]).parent / "bootstrap_fail.sh"
    failing_bootstrap.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'echo "bootstrap" >> "{env["PIP_AUDIT_BOOTSTRAP_LOG"]}"\n'
        "exit 42\n",
        encoding="utf-8",
    )
    failing_bootstrap.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    env["PIP_AUDIT_BOOTSTRAP"] = str(failing_bootstrap)

    result = subprocess.run(
        [str(_SCRIPT_PATH)],
        cwd=_SCRIPT_PATH.parent.parent.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Automatic installation of pip-audit failed" in result.stderr
