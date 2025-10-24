"""Tests for environment helper utilities in :mod:`app.main`."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.main as main


@pytest.mark.parametrize(
    "raw_value",
    ["1", "true", "TRUE", " yes ", "On"],
)
def test_parse_bool_env_truthy(monkeypatch: pytest.MonkeyPatch, raw_value: str) -> None:
    monkeypatch.setattr(main, "get_env", lambda name: raw_value)

    assert main._parse_bool_env("HARMONY_INIT_DB") is True


@pytest.mark.parametrize(
    "raw_value",
    ["0", "false", "FALSE", " no ", "Off"],
)
def test_parse_bool_env_falsy(monkeypatch: pytest.MonkeyPatch, raw_value: str) -> None:
    monkeypatch.setattr(main, "get_env", lambda name: raw_value)

    assert main._parse_bool_env("HARMONY_INIT_DB") is False


@pytest.mark.parametrize("raw_value", ["", "   ", "maybe", "10"])
def test_parse_bool_env_invalid(monkeypatch: pytest.MonkeyPatch, raw_value: str) -> None:
    monkeypatch.setattr(main, "get_env", lambda name: raw_value)

    assert main._parse_bool_env("HARMONY_INIT_DB") is None


@pytest.mark.parametrize("override_value, expected", [("true", True), ("0", False)])
def test_should_initialize_database_honours_override(
    monkeypatch: pytest.MonkeyPatch, override_value: str, expected: bool
) -> None:
    config = SimpleNamespace(environment=SimpleNamespace(is_test=True))
    monkeypatch.setattr(main, "get_env", lambda name: override_value)

    assert main._should_initialize_database(config) is expected


def test_should_initialize_database_defaults_by_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    config_test = SimpleNamespace(environment=SimpleNamespace(is_test=True))
    config_non_test = SimpleNamespace(environment=SimpleNamespace(is_test=False))
    monkeypatch.setattr(main, "get_env", lambda name: None)

    assert main._should_initialize_database(config_test) is False
    assert main._should_initialize_database(config_non_test) is True


def test_resolve_watchlist_interval_uses_default() -> None:
    assert main._resolve_watchlist_interval(None) == 86_400.0


def test_resolve_watchlist_interval_honours_override() -> None:
    override = 123.45

    assert main._resolve_watchlist_interval(override) == override


@pytest.mark.parametrize("override, expected", [(None, 42), (1, 5), (30, 30)])
def test_resolve_visibility_timeout_clamps_to_minimum(
    monkeypatch: pytest.MonkeyPatch, override: int | None, expected: int
) -> None:
    fake_settings = SimpleNamespace(
        orchestrator=SimpleNamespace(visibility_timeout_s=42),
    )
    monkeypatch.setattr(main, "settings", fake_settings)

    assert main._resolve_visibility_timeout(override) == expected
