"""Sanity checks ensuring app.core modules import without side-effects."""

from __future__ import annotations

import importlib
from pathlib import Path
import pkgutil

import pytest

_MODULE_ROOT = Path(__file__).resolve().parents[2] / "app" / "core"


def _discover_modules() -> list[str]:
    modules: list[str] = []
    for module in pkgutil.iter_modules([str(_MODULE_ROOT)]):
        name = module.name
        if name.startswith("__"):
            continue
        modules.append(name)
    return sorted(modules)


@pytest.mark.parametrize("module_name", _discover_modules())
def test_app_core_imports(module_name: str) -> None:
    importlib.import_module(f"app.core.{module_name}")
