"""Tests for ``scripts/dev/sync_runtime_requirements.py``."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.dev import sync_runtime_requirements as sync


def _prepare_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pyproject_contents: str,
) -> Path:
    pyproject_path = tmp_path / "pyproject.toml"
    requirements_path = tmp_path / "requirements.txt"
    pyproject_path.write_text(pyproject_contents, encoding="utf-8")
    requirements_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(sync, "PYPROJECT_PATH", pyproject_path)
    monkeypatch.setattr(sync, "REQUIREMENTS_PATH", requirements_path)
    return requirements_path


def test_check_accepts_allowlisted_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requirements_path = _prepare_environment(
        tmp_path,
        monkeypatch,
        pyproject_contents="""
[project]
dependencies = [
    "starlette==0.49.1",
    "anyio==3.7.1",
]
""",
    )

    sync.sync_dependencies(check_only=False)
    sync.sync_dependencies(check_only=True)

    contents = requirements_path.read_text("utf-8")
    assert "starlette==0.49.1" in contents


def test_check_rejects_allowlisted_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requirements_path = _prepare_environment(
        tmp_path,
        monkeypatch,
        pyproject_contents="""
[project]
dependencies = [
    "starlette==0.49.1",
    "anyio==3.7.1",
]
""",
    )

    sync.sync_dependencies(check_only=False)
    original = requirements_path.read_text("utf-8")
    requirements_path.write_text(
        original.replace("starlette==0.49.1", "starlette<0.49.1"),
        encoding="utf-8",
    )

    with pytest.raises(sync.DependencySyncError):
        sync.sync_dependencies(check_only=True)
