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


@pytest.mark.parametrize(
    "alias_name",
    ["PORT", "UVICORN_PORT", "SERVICE_PORT", "WEB_PORT", "FRONTEND_PORT"],
)
def test_resolve_app_port_accepts_legacy_aliases(alias_name: str) -> None:
    """Legacy aliases are normalised when APP_PORT is unset."""

    assert resolve_app_port({alias_name: "9091"}) == 9091


def test_resolve_app_port_prefers_app_port_over_alias() -> None:
    """APP_PORT remains authoritative when aliases are present."""

    assert resolve_app_port({"APP_PORT": "8088", "PORT": "9092"}) == 8088


def test_resolve_app_port_ignores_empty_aliases() -> None:
    """Blank alias values are treated as absent."""

    assert resolve_app_port({"PORT": "   ", "APP_PORT": "9000"}) == 9000
