"""Tests for configuration validation during Harmony startup."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.main as main
from app.runtime.paths import SQLITE_DATABASE_URL


def _make_config(url: str | None) -> SimpleNamespace:
    return SimpleNamespace(database=SimpleNamespace(url=url))


def test_load_validated_config_accepts_sqlite_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config(SQLITE_DATABASE_URL)
    monkeypatch.setattr(main, "load_config", lambda: config)

    assert main._load_validated_config() is config


def test_load_validated_config_rejects_non_sqlite_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_url = "sqlite:///other-location/harmony.db"
    config = _make_config(configured_url)
    mock_logger = Mock()

    monkeypatch.setattr(main, "load_config", lambda: config)
    monkeypatch.setattr(main, "logger", mock_logger)

    with pytest.raises(RuntimeError):
        main._load_validated_config()

    mock_logger.critical.assert_called_once()
    message_args = mock_logger.critical.call_args[0]
    assert message_args and "unsupported database URL" in message_args[0]
    assert mock_logger.critical.call_args.kwargs["extra"] == {
        "event": "startup.database_url_mismatch",
        "configured_url": configured_url,
        "expected_url": SQLITE_DATABASE_URL,
    }
