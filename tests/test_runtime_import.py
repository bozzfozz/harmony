"""Smoke tests verifying that core runtime dependencies import correctly."""

from __future__ import annotations

import importlib


def test_imports_fastapi_and_starlette() -> None:
    """Ensure the pinned FastAPI and Starlette packages import successfully."""

    fastapi = importlib.import_module("fastapi")
    starlette = importlib.import_module("starlette")

    assert hasattr(fastapi, "FastAPI")
    assert hasattr(starlette, "__version__")


def test_app_factory_import() -> None:
    """Verify that the Harmony app module exposes an ASGI application factory."""

    app_mod = importlib.import_module("app.main")
    app = getattr(app_mod, "app", None) or getattr(app_mod, "create_app", None)

    assert app is not None
