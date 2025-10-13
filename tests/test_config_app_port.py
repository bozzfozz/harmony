"""Tests for resolving the canonical application port."""

import pytest

from app.config import DEFAULT_APP_PORT, resolve_app_port


def test_resolve_app_port_defaults_to_constant() -> None:
    """The resolver returns the default port when unset."""

    assert resolve_app_port({}) == DEFAULT_APP_PORT


def test_resolve_app_port_respects_environment_override() -> None:
    """Explicit environment values override the default when valid."""

    assert resolve_app_port({"APP_PORT": "9090"}) == 9090


def test_resolve_app_port_clamps_invalid_values() -> None:
    """Non-numeric values fall back to the default port."""

    assert resolve_app_port({"APP_PORT": "not-a-port"}) == DEFAULT_APP_PORT


def test_resolve_app_port_supports_legacy_port_alias() -> None:
    """Legacy `PORT` values are treated as APP_PORT when unset."""

    assert resolve_app_port({"PORT": "9091"}) == 9091


def test_resolve_app_port_supports_uvicorn_alias() -> None:
    """Legacy uvicorn-specific aliases are accepted when APP_PORT is absent."""

    assert resolve_app_port({"UVICORN_PORT": "8123"}) == 8123


def test_resolve_app_port_rejects_conflicting_alias() -> None:
    """Setting APP_PORT alongside a conflicting alias raises an error."""

    with pytest.raises(ValueError):
        resolve_app_port({"APP_PORT": "8080", "PORT": "9090"})


def test_resolve_app_port_invalid_alias_value_falls_back() -> None:
    """Legacy aliases with invalid values fall back to the default."""

    assert resolve_app_port({"PORT": "invalid"}) == DEFAULT_APP_PORT
