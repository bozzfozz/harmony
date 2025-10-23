"""Verify admin router registration respects the feature flag."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.admin_artists import maybe_register_admin_routes
from app.config import AppConfig, load_config


def _config_with_admin(enabled: bool) -> AppConfig:
    env = {
        "APP_ENV": "test",
        "FEATURE_ADMIN_API": "1" if enabled else "0",
    }
    return load_config(runtime_env=env)


def _admin_paths(routes: Iterable[APIRoute]) -> set[str]:
    return {route.path for route in routes if route.path.startswith("/admin")}


def test_admin_routes_absent_when_feature_disabled() -> None:
    app = FastAPI()
    config = _config_with_admin(enabled=False)

    registered = maybe_register_admin_routes(app, config=config)

    assert registered is False
    assert getattr(app.state, "admin_artists_registered", False) is False
    assert _admin_paths(app.router.routes) == set()

    with TestClient(app) as client:
        response = client.get("/admin/artists")
    assert response.status_code == 404


def test_admin_routes_registered_when_feature_enabled() -> None:
    app = FastAPI()
    config = _config_with_admin(enabled=True)

    registered = maybe_register_admin_routes(app, config=config)

    assert registered is True
    assert getattr(app.state, "admin_artists_registered", False) is True

    admin_paths = _admin_paths(app.router.routes)
    assert admin_paths
    assert any(path.startswith("/admin/artists") for path in admin_paths)

    stored_routes = getattr(app.state, "admin_artists_routes", ())
    assert stored_routes
    assert all(route.path in admin_paths for route in stored_routes)
