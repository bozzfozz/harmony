"""Tests for auto-repair engine utilities and fixers."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

import pytest

import scripts.auto_repair.engine as auto_repair_engine


def _prepare_env(monkeypatch: pytest.MonkeyPatch, overrides: Mapping[str, str]) -> None:
    for key in ("CI", "SUPPLY_MODE", "TOOLCHAIN_STRICT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize(
    ("env", "expected_warn"),
    [
        ({"CI": "true"}, False),
        ({"CI": "true", "SUPPLY_MODE": "WARN"}, True),
        ({"CI": "true", "TOOLCHAIN_STRICT": "0"}, True),
        ({"CI": "true", "TOOLCHAIN_STRICT": "false"}, True),
        ({"CI": "true", "SUPPLY_MODE": "strict"}, False),
        ({"CI": "true", "SUPPLY_MODE": "STRICT", "TOOLCHAIN_STRICT": "1"}, False),
        ({"CI": "true", "SUPPLY_MODE": "WARN", "TOOLCHAIN_STRICT": "1"}, True),
    ],
)
def test_determine_warn_mode_behaviour(
    monkeypatch: pytest.MonkeyPatch, env: Mapping[str, str], expected_warn: bool
) -> None:
    _prepare_env(monkeypatch, env)
    assert auto_repair_engine.determine_warn_mode() is expected_warn


def test_default_strict_when_ci_truthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare_env(monkeypatch, {"CI": "1"})
    assert auto_repair_engine.determine_warn_mode() is False


class _SilentLogger(auto_repair_engine.ReasonTraceLogger):
    """Logger stub that suppresses output during tests."""

    def emit(self, **_: object) -> None:  # type: ignore[override]
        return


def _make_context(stderr: str) -> auto_repair_engine.RepairContext:
    command = auto_repair_engine.RepairCommand(name="pytest", argv=["pytest"])
    stage = auto_repair_engine.RepairStage(name="test", commands=(command,))
    result = auto_repair_engine.CommandResult(returncode=2, stdout="", stderr=stderr)
    return auto_repair_engine.RepairContext(
        stage=stage,
        command=command,
        attempt=1,
        result=result,
        combined_output=f"\n{stderr}",
        env={},
    )


def test_pytest_cov_fixer_installs_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auto_repair_engine, "_resolve_pytest_cov_requirement", lambda: "pytest-cov==4.1.0"
    )
    recorded: dict[str, list[str]] = {}

    def _patched_run(command, **_: object) -> SimpleNamespace:  # type: ignore[override]
        recorded["command"] = command
        return SimpleNamespace(returncode=0, stdout="installed", stderr="")

    monkeypatch.setattr(auto_repair_engine.subprocess, "run", _patched_run)

    stderr = "pytest: error: unrecognized arguments: --cov=app"
    context = _make_context(stderr)
    fixer = auto_repair_engine.PytestCovFixer()
    assert fixer.matches(context)

    outcome = fixer.apply(context, _SilentLogger())

    assert outcome.success is True
    assert outcome.commands == ["pip install pytest-cov==4.1.0"]
    assert recorded["command"] == ["pip", "install", "pytest-cov==4.1.0"]


def test_pytest_cov_fixer_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auto_repair_engine, "_resolve_pytest_cov_requirement", lambda: "pytest-cov")

    def _failing_run(command, **_: object) -> SimpleNamespace:  # type: ignore[override]
        return SimpleNamespace(returncode=1, stdout="", stderr="error: network down")

    monkeypatch.setattr(auto_repair_engine.subprocess, "run", _failing_run)

    stderr = "pytest: error: unrecognized arguments: --cov-report=term"
    context = _make_context(stderr)
    fixer = auto_repair_engine.PytestCovFixer()
    assert fixer.matches(context)

    outcome = fixer.apply(context, _SilentLogger())

    assert outcome.success is False
    assert outcome.commands == ["pip install pytest-cov"]
    assert "error: network down" in outcome.message
    assert outcome.warnings
