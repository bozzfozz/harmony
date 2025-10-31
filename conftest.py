"""Project-wide pytest configuration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Final


def _builtin_pytest_cov_plugin() -> Path:
    return Path(__file__).resolve().parent / "pytest_cov" / "plugin.py"


def _should_register_builtin_pytest_cov() -> bool:
    """Return True when the repository's fallback pytest-cov plugin should load."""

    expected = _builtin_pytest_cov_plugin()
    spec = importlib.util.find_spec("pytest_cov.plugin")
    if spec is None or spec.origin is None:
        return False

    try:
        origin = Path(spec.origin).resolve()
    except OSError:
        return False

    return origin == expected


if _should_register_builtin_pytest_cov():
    _plugins: tuple[str, ...] = ("pytest_cov.plugin",)
else:
    _plugins = tuple()

pytest_plugins: Final[tuple[str, ...]] = _plugins
