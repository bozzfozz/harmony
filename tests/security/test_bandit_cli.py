"""Tests für die offline-fähige Bandit-CLI."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

import bandit.cli as bandit_cli


pytestmark = pytest.mark.no_postgres


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    config = tmp_path / ".bandit"
    config.write_text(
        """
[bandit]
severity = LOW
confidence = LOW
exclude = tests
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config


def test_cli_reports_no_findings(tmp_path: Path, config_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "safe_module.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = bandit_cli.main(["-c", str(config_file), "-r", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No issues identified" in captured.out


def test_cli_flags_eval_usage(tmp_path: Path, config_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "suspicious.py").write_text("def run(code):\n    return eval(code)\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = bandit_cli.main(["-c", str(config_file), "-r", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "B101" in captured.out
    assert "eval()" in captured.out


def test_cli_honours_exclude_patterns(tmp_path: Path, config_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    excluded_dir = tmp_path / "tests"
    excluded_dir.mkdir()
    (excluded_dir / "fixture.py").write_text("eval('42')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = bandit_cli.main(["-c", str(config_file), "-r", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No issues identified" in captured.out


def test_wrapper_script_executes_cli(tmp_path: Path, config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    script = repository_root / "scripts" / "bandit.py"
    (tmp_path / "checked.py").write_text("print('secure')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    completed = subprocess.run(
        [sys.executable, str(script), "-c", str(config_file), "-r", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "No issues identified" in completed.stdout
