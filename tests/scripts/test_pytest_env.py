from __future__ import annotations

import importlib
from pathlib import Path
import sys

import pytest

from scripts.dev import pytest_env


def test_ensure_pytest_cov_no_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    result = pytest_env.ensure_pytest_cov(pytest_addopts="")

    assert result.required is False
    assert result.installed is True
    assert result.command is None
    assert result.env_updates == {}


def test_ensure_pytest_cov_detects_external_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pytest_env, "_ensure_pytest_cov_available", lambda: True)
    monkeypatch.setattr(pytest_env, "_using_builtin_pytest_cov", lambda: False)
    monkeypatch.delenv("PYTHONPATH", raising=False)

    result = pytest_env.ensure_pytest_cov(pytest_addopts="--cov=app")

    assert result.required is True
    assert result.installed is False
    assert result.command is None
    assert "External pytest-cov" in result.message
    assert result.env_updates.get("PYTHONPATH") == str(pytest_env.REPO_ROOT)


def test_ensure_pytest_cov_reports_missing_builtin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pytest_env, "_ensure_pytest_cov_available", lambda: False)
    monkeypatch.delenv("PYTHONPATH", raising=False)

    result = pytest_env.ensure_pytest_cov(pytest_addopts="--cov-report=term")

    assert result.required is True
    assert result.installed is False
    assert result.command is None
    assert "bundled pytest-cov plugin could not be loaded" in result.message
    assert result.env_updates.get("PYTHONPATH") == str(pytest_env.REPO_ROOT)


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

    monkeypatch.setattr(pytest_env.importlib, "import_module", _import)

    monkeypatch.delenv("PYTHONPATH", raising=False)

    result = pytest_env.ensure_pytest_cov(pytest_addopts="--cov=app")

    assert result.required is True
    assert result.installed is True
    assert result.command is None
    assert result.message == "pytest-cov already available"
    assert repo_path in sys.path
    assert result.env_updates["PYTEST_ADDOPTS"] == "--cov=app -p pytest_cov.plugin"
    assert result.env_updates["PYTHONPATH"].startswith(repo_path)


def test_ensure_pytest_cov_does_not_duplicate_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "--cov=app -p pytest_cov.plugin")
    monkeypatch.setenv("PYTHONPATH", str(pytest_env.REPO_ROOT))

    result = pytest_env.ensure_pytest_cov(pytest_addopts=None)

    assert result.required is True
    assert result.installed is True
    assert result.env_updates == {}
