"""Project-wide pytest configuration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Final


def _builtin_pytest_cov_package() -> Path:
    return Path(__file__).resolve().parent / "pytest_cov"


def _load_module(name: str, path: Path, *, package: bool = False) -> ModuleType | None:
    spec = importlib.util.spec_from_file_location(
        name,
        path,
        submodule_search_locations=[str(path.parent)] if package else None,
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    try:
        loader.exec_module(module)  # type: ignore[call-arg]
    except OSError:
        return None
    sys.modules[name] = module
    return module


def _ensure_builtin_pytest_cov() -> bool:
    """Ensure Harmony's pytest-cov shim is importable as ``pytest_cov``."""

    expected_plugin = _builtin_pytest_cov_package() / "plugin.py"

    try:
        existing = importlib.util.find_spec("pytest_cov.plugin")
    except (ImportError, AttributeError):
        existing = None

    if existing is not None and existing.origin is not None:
        try:
            origin = Path(existing.origin).resolve()
        except OSError:
            origin = None
        else:
            if origin == expected_plugin:
                return True

    module = sys.modules.get("pytest_cov.plugin")
    if module is not None and hasattr(module, "HarmonyCoveragePlugin"):
        return True

    package_dir = _builtin_pytest_cov_package()
    package_init = package_dir / "__init__.py"
    package = _load_module("pytest_cov", package_init, package=True)
    if package is None:
        return False
    plugin = _load_module("pytest_cov.plugin", expected_plugin)
    if plugin is None:
        return False
    setattr(package, "plugin", plugin)
    return hasattr(plugin, "HarmonyCoveragePlugin")


if _ensure_builtin_pytest_cov():
    _plugins: tuple[str, ...] = ("pytest_cov.plugin",)
else:
    _plugins = tuple()

pytest_plugins: Final[tuple[str, ...]] = _plugins
