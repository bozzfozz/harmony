"""Helpers for preparing the pytest execution environment."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
import os
from pathlib import Path
import shlex
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class PytestCovSetupResult:
    """Outcome of preparing pytest-cov for a test run."""

    required: bool
    installed: bool
    command: tuple[str, ...] | None
    message: str
    env_updates: dict[str, str]
def _coverage_requested(pytest_addopts: str) -> bool:
    return "--cov" in pytest_addopts or "--cov-report" in pytest_addopts


def _ensure_repo_on_syspath() -> None:
    repo_path = str(REPO_ROOT)
    if repo_path not in sys.path:
        sys.path.insert(0, repo_path)


def _pythonpath_with_repo(existing: str | None) -> str | None:
    """Return a PYTHONPATH string that ensures the repo is importable."""

    repo_path = str(REPO_ROOT)
    if not existing:
        return repo_path

    entries = [entry for entry in existing.split(os.pathsep) if entry]
    if repo_path in entries:
        return None
    return os.pathsep.join([repo_path, existing])


def _inject_plugin_flag(pytest_addopts: str) -> tuple[str, bool]:
    """Ensure the built-in coverage plugin is explicitly loaded via -p."""

    tokens = shlex.split(pytest_addopts) if pytest_addopts else []
    plugin_name = "pytest_cov.plugin"

    for index, token in enumerate(tokens):
        if token == "-p":
            if index + 1 < len(tokens) and tokens[index + 1] == plugin_name:
                return pytest_addopts, False
        elif token.startswith("-p"):
            value = token[2:]
            if value.startswith("="):
                value = value[1:]
            if value == plugin_name or value == f"no:{plugin_name}":
                if value == plugin_name:
                    return pytest_addopts, False
    tokens.extend(["-p", plugin_name])
    new_addopts = " ".join(shlex.quote(token) for token in tokens)
    return new_addopts, True


def _builtin_pytest_cov_plugin() -> Path:
    return REPO_ROOT / "pytest_cov" / "plugin.py"


def _using_builtin_pytest_cov() -> bool:
    """Return True when the repository-provided pytest-cov plugin is active."""

    spec = importlib.util.find_spec("pytest_cov.plugin")
    if spec is None or spec.origin is None:
        return False

    try:
        origin = Path(spec.origin).resolve()
    except OSError:
        return False

    try:
        builtin = _builtin_pytest_cov_plugin().resolve()
    except OSError:
        return False

    return origin == builtin


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
    env_updates: dict[str, str] = {}
    if not addopts:
        return PytestCovSetupResult(
            required=False,
            installed=True,
            command=None,
            message="Coverage flags not requested",
            env_updates=env_updates,
        )

    addopts = addopts.strip()
    required = _coverage_requested(addopts)
    if not required:
        return PytestCovSetupResult(
            required=False,
            installed=True,
            command=None,
            message="Coverage flags not requested",
            env_updates=env_updates,
        )

    if _ensure_pytest_cov_available():
        if not _using_builtin_pytest_cov():
            pythonpath_update = _pythonpath_with_repo(os.getenv("PYTHONPATH"))
            if pythonpath_update is not None:
                env_updates["PYTHONPATH"] = pythonpath_update
            return PytestCovSetupResult(
                required=True,
                installed=False,
                command=None,
                message=(
                    "External pytest-cov package detected; uninstall it to use Harmony's "
                    "built-in coverage plugin."
                ),
                env_updates=env_updates,
            )

        updated_addopts, mutated = _inject_plugin_flag(addopts)
        if mutated:
            env_updates["PYTEST_ADDOPTS"] = updated_addopts
        pythonpath_update = _pythonpath_with_repo(os.getenv("PYTHONPATH"))
        if pythonpath_update is not None:
            env_updates["PYTHONPATH"] = pythonpath_update
        return PytestCovSetupResult(
            required=True,
            installed=True,
            command=None,
            message="pytest-cov already available",
            env_updates=env_updates,
        )

    pythonpath_update = _pythonpath_with_repo(os.getenv("PYTHONPATH"))
    if pythonpath_update is not None:
        env_updates["PYTHONPATH"] = pythonpath_update
    return PytestCovSetupResult(
        required=True,
        installed=False,
        command=None,
        message=(
            "Harmony's bundled pytest-cov plugin could not be loaded; ensure the repository "
            "is available on PYTHONPATH and reinstall the package if necessary."
        ),
        env_updates=env_updates,
    )
