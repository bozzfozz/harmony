"""Tests for auto-repair engine utilities and fixers."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

import pytest

import scripts.auto_repair.engine as auto_repair_engine
from scripts.dev import pytest_env


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


def _make_context(
    stderr: str, env: Mapping[str, str] | None = None
) -> auto_repair_engine.RepairContext:
    command = auto_repair_engine.RepairCommand(name="pytest", argv=["pytest"])
    stage = auto_repair_engine.RepairStage(name="test", commands=(command,))
    result = auto_repair_engine.CommandResult(returncode=2, stdout="", stderr=stderr)
    return auto_repair_engine.RepairContext(
        stage=stage,
        command=command,
        attempt=1,
        result=result,
        combined_output=f"\n{stderr}",
        env=dict(env or {}),
    )


def test_pytest_cov_fixer_installs_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _patched_ensure(addopts: str | None = None) -> pytest_env.PytestCovSetupResult:
        captured["addopts"] = addopts
        return pytest_env.PytestCovSetupResult(
            required=True,
            installed=True,
            command=("pip", "install", "pytest-cov==4.1.0"),
            message="Installed pytest-cov",
            env_updates={"PYTEST_ADDOPTS": "--cov=app -p pytest_cov.plugin"},
        )

    monkeypatch.setattr(auto_repair_engine.pytest_env, "ensure_pytest_cov", _patched_ensure)

    stderr = "pytest: error: unrecognized arguments: --cov=app"
    context = _make_context(stderr, {"PYTEST_ADDOPTS": "--cov=app"})
    fixer = auto_repair_engine.PytestCovFixer()
    assert fixer.matches(context)

    outcome = fixer.apply(context, _SilentLogger())

    assert outcome.success is True
    assert outcome.commands == ["pip install pytest-cov==4.1.0"]
    assert captured["addopts"] == "--cov=app"


def test_pytest_cov_fixer_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _patched_ensure(addopts: str | None = None) -> pytest_env.PytestCovSetupResult:
        return pytest_env.PytestCovSetupResult(
            required=True,
            installed=False,
            command=("pip", "install", "pytest-cov"),
            message="error: network down",
            env_updates={},
        )

    monkeypatch.setattr(auto_repair_engine.pytest_env, "ensure_pytest_cov", _patched_ensure)

    stderr = "pytest: error: unrecognized arguments: --cov-report=term"
    context = _make_context(stderr, {"PYTEST_ADDOPTS": "--cov-report=term"})
    fixer = auto_repair_engine.PytestCovFixer()
    assert fixer.matches(context)

    outcome = fixer.apply(context, _SilentLogger())

    assert outcome.success is False
    assert outcome.commands == ["pip install pytest-cov"]
    assert "error: network down" in outcome.message
    assert outcome.warnings


def test_pytest_cov_fixer_matches_modulenotfound() -> None:
    stderr = "ModuleNotFoundError: No module named 'pytest_cov'"
    context = _make_context(stderr)
    fixer = auto_repair_engine.PytestCovFixer()
    assert fixer.matches(context)


def test_engine_aborts_when_pytest_cov_setup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    stage = auto_repair_engine.RepairStage(
        name="test",
        commands=(),
    )
    engine = auto_repair_engine.AutoRepairEngine(
        stages={"test": stage},
        fixers=(),
        max_iters=1,
        logger=_SilentLogger(),
    )

    failure = pytest_env.PytestCovSetupResult(
        required=True,
        installed=False,
        command=("pip", "install", "pytest-cov"),
        message="network down",
        env_updates={},
    )

    monkeypatch.setattr(auto_repair_engine.pytest_env, "ensure_pytest_cov", lambda _: failure)

    exit_code = engine.run("test")

    assert exit_code == 1


def test_engine_applies_pytest_cov_env_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    stage = auto_repair_engine.RepairStage(
        name="test",
        commands=(auto_repair_engine.RepairCommand(name="pytest", argv=("pytest",)),),
    )
    engine = auto_repair_engine.AutoRepairEngine(
        stages={"test": stage},
        fixers=(),
        max_iters=1,
        logger=_SilentLogger(),
    )

    recorded: dict[str, object] = {}

    def _fake_run(argv, *, cwd, env, capture_output, text, check):  # type: ignore[override]
        recorded["env"] = env
        recorded["argv"] = argv
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(auto_repair_engine.subprocess, "run", _fake_run)

    setup = pytest_env.PytestCovSetupResult(
        required=True,
        installed=True,
        command=None,
        message="built-in",
        env_updates={"PYTEST_ADDOPTS": "--cov=app -p pytest_cov.plugin"},
    )
    monkeypatch.setattr(auto_repair_engine.pytest_env, "ensure_pytest_cov", lambda _: setup)

    exit_code = engine.run("test")

    assert exit_code == 0
    assert recorded["env"]["PYTEST_ADDOPTS"] == "--cov=app -p pytest_cov.plugin"
