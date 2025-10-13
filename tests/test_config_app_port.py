"""Tests for resolving the canonical application port."""

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
