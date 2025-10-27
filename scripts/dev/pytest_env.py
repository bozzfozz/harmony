"""Helpers for preparing the pytest execution environment."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import subprocess
import textwrap

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class PytestCovSetupResult:
    """Outcome of preparing pytest-cov for a test run."""

    required: bool
    installed: bool
    command: tuple[str, ...] | None
    message: str


def resolve_pytest_cov_requirement() -> str:
    """Return the pinned pytest-cov requirement string, if available."""

    requirement_file = REPO_ROOT / "requirements-test.txt"
    if not requirement_file.exists():
        return "pytest-cov"

    for raw_line in requirement_file.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        token, *_ = stripped.split()
        if token.startswith("pytest-cov"):
            return token

    return "pytest-cov"


def _coverage_requested(pytest_addopts: str) -> bool:
    return "--cov" in pytest_addopts or "--cov-report" in pytest_addopts


def ensure_pytest_cov(pytest_addopts: str | None = None) -> PytestCovSetupResult:
    """Ensure pytest-cov is available when coverage flags are present."""

    addopts = pytest_addopts if pytest_addopts is not None else os.getenv("PYTEST_ADDOPTS") or ""
    if not addopts:
        return PytestCovSetupResult(
            required=False, installed=True, command=None, message="Coverage flags not requested"
        )

    addopts = addopts.strip()
    required = _coverage_requested(addopts)
    if not required:
        return PytestCovSetupResult(
            required=False, installed=True, command=None, message="Coverage flags not requested"
        )

    try:
        importlib.import_module("pytest_cov")
        return PytestCovSetupResult(
            required=True,
            installed=True,
            command=None,
            message="pytest-cov already available",
        )
    except ModuleNotFoundError:
        requirement = resolve_pytest_cov_requirement()
        command = ("pip", "install", requirement)
        completed = subprocess.run(
            list(command),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            importlib.invalidate_caches()
            try:
                importlib.import_module("pytest_cov")
            except ModuleNotFoundError:
                return PytestCovSetupResult(
                    required=True,
                    installed=False,
                    command=command,
                    message="pytest-cov installation reported success but module still missing",
                )
            return PytestCovSetupResult(
                required=True,
                installed=True,
                command=command,
                message="Installed pytest-cov",
            )

        message = textwrap.shorten(
            (completed.stderr or completed.stdout or "pip install pytest-cov failed").strip(),
            width=240,
        )
        return PytestCovSetupResult(
            required=True,
            installed=False,
            command=command,
            message=message,
        )
