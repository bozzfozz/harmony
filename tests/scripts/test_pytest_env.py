from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from scripts.dev import pytest_env


def test_ensure_pytest_cov_no_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    result = pytest_env.ensure_pytest_cov(pytest_addopts="")

    assert result.required is False
    assert result.installed is True
    assert result.command is None


def test_ensure_pytest_cov_installs_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    call_state: dict[str, object] = {"import_calls": 0}

    def _fake_import(name: str, package: str | None = None) -> None:
        if name != "pytest_cov":
            raise AssertionError(f"Unexpected import: {name}")
        call_state["import_calls"] = call_state.get("import_calls", 0) + 1
        if call_state["import_calls"] <= 2:
            raise ModuleNotFoundError

    monkeypatch.setattr(pytest_env.importlib, "import_module", _fake_import)
    monkeypatch.setattr(pytest_env.importlib, "invalidate_caches", lambda: None)
    monkeypatch.setattr(pytest_env, "resolve_pytest_cov_requirement", lambda: "pytest-cov==4.1.0")
    monkeypatch.setattr(pytest_env, "_load_builtin_pytest_cov", lambda: False)

    def _fake_run(command, **_: object) -> SimpleNamespace:  # type: ignore[override]
        monkeypatch.setattr(
            pytest_env.importlib,
            "import_module",
            lambda name, package=None: SimpleNamespace() if name == "pytest_cov" else None,
        )
        return SimpleNamespace(returncode=0, stdout="installed", stderr="")

    monkeypatch.setattr(pytest_env.subprocess, "run", _fake_run)

    result = pytest_env.ensure_pytest_cov(pytest_addopts="--cov=app")

    assert result.required is True
    assert result.installed is True
    assert result.command == ("pip", "install", "pytest-cov==4.1.0")
    assert result.message == "Installed pytest-cov"


def test_ensure_pytest_cov_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pytest_env.importlib, "invalidate_caches", lambda: None)

    def _always_missing(name: str, package: str | None = None) -> None:
        raise ModuleNotFoundError

    monkeypatch.setattr(pytest_env.importlib, "import_module", _always_missing)
    monkeypatch.setattr(pytest_env, "resolve_pytest_cov_requirement", lambda: "pytest-cov")
    monkeypatch.setattr(pytest_env, "_load_builtin_pytest_cov", lambda: False)

    def _failing_run(command, **_: object) -> SimpleNamespace:  # type: ignore[override]
        return SimpleNamespace(returncode=1, stdout="", stderr="network down")

    monkeypatch.setattr(pytest_env.subprocess, "run", _failing_run)

    result = pytest_env.ensure_pytest_cov(pytest_addopts="--cov-report=term")

    assert result.required is True
    assert result.installed is False
    assert result.command == ("pip", "install", "pytest-cov")
    assert "network down" in result.message


def test_ensure_pytest_cov_uses_builtin_package(monkeypatch: pytest.MonkeyPatch) -> None:
    repo_path = str(pytest_env.REPO_ROOT)
    filtered_path = [entry for entry in sys.path if Path(entry).resolve() != pytest_env.REPO_ROOT]
    monkeypatch.setattr(sys, "path", filtered_path)
    monkeypatch.setattr(pytest_env.sys, "path", filtered_path)

    for name in list(sys.modules):
        if name == "pytest_cov" or name.startswith("pytest_cov."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    real_import_module = importlib.import_module
    state = {"calls": 0}

    def _import(name: str, package: str | None = None):
        if name == "pytest_cov":
            state["calls"] += 1
            if state["calls"] == 1:
                raise ModuleNotFoundError
        return real_import_module(name, package)

    def _fail_run(*_: object, **__: object) -> None:
        raise AssertionError("pip install should not run when builtin pytest-cov is available")

    monkeypatch.setattr(pytest_env.importlib, "import_module", _import)
    monkeypatch.setattr(pytest_env.subprocess, "run", _fail_run)

    result = pytest_env.ensure_pytest_cov(pytest_addopts="--cov=app")

    assert result.required is True
    assert result.installed is True
    assert result.command is None
    assert result.message == "pytest-cov already available"
    assert repo_path in sys.path
