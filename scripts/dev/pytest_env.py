"""Helpers for preparing the pytest execution environment."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
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


def _ensure_repo_on_syspath() -> None:
    repo_path = str(REPO_ROOT)
    if repo_path not in sys.path:
        sys.path.insert(0, repo_path)


def _import_pytest_cov_module() -> bool:
    try:
        importlib.import_module("pytest_cov")
        return True
    except ModuleNotFoundError:
        return False


def _load_builtin_pytest_cov() -> bool:
    package_dir = REPO_ROOT / "pytest_cov"
    init_file = package_dir / "__init__.py"
    if not init_file.exists():
        return False

    spec = importlib.util.spec_from_file_location(
        "pytest_cov",
        init_file,
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        return False

    module = importlib.util.module_from_spec(spec)
    sys.modules["pytest_cov"] = module
    spec.loader.exec_module(module)

    try:
        importlib.import_module("pytest_cov.plugin")
    except ModuleNotFoundError:
        return False
    return True


def _ensure_pytest_cov_available() -> bool:
    if _import_pytest_cov_module():
        return True

    _ensure_repo_on_syspath()
    if _import_pytest_cov_module():
        return True

    return _load_builtin_pytest_cov()


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

    if _ensure_pytest_cov_available():
        return PytestCovSetupResult(
            required=True,
            installed=True,
            command=None,
            message="pytest-cov already available",
        )
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
        if _ensure_pytest_cov_available():
            return PytestCovSetupResult(
                required=True,
                installed=True,
                command=command,
                message="Installed pytest-cov",
            )
        return PytestCovSetupResult(
            required=True,
            installed=False,
            command=command,
            message="pytest-cov installation reported success but module still missing",
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
