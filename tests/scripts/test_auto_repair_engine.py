"""Tests for the auto-repair engine configuration helpers."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from scripts.auto_repair.engine import determine_warn_mode


def _prepare_env(monkeypatch: pytest.MonkeyPatch, overrides: Mapping[str, str]) -> None:
    for key in ("CI", "SUPPLY_MODE", "TOOLCHAIN_STRICT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize(
    ("env", "expected_warn"),
    [
        ({"CI": "true"}, False),
        ({"CI": "true", "SUPPLY_MODE": "WARN"}, True),
        ({"CI": "true", "TOOLCHAIN_STRICT": "0"}, True),
        ({"CI": "true", "TOOLCHAIN_STRICT": "false"}, True),
        ({"CI": "true", "SUPPLY_MODE": "strict"}, False),
        ({"CI": "true", "SUPPLY_MODE": "STRICT", "TOOLCHAIN_STRICT": "1"}, False),
        ({"CI": "true", "SUPPLY_MODE": "WARN", "TOOLCHAIN_STRICT": "1"}, True),
    ],
)
def test_determine_warn_mode_behaviour(
    monkeypatch: pytest.MonkeyPatch, env: Mapping[str, str], expected_warn: bool
) -> None:
    _prepare_env(monkeypatch, env)
    assert determine_warn_mode() is expected_warn


def test_default_strict_when_ci_truthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare_env(monkeypatch, {"CI": "1"})
    assert determine_warn_mode() is False
