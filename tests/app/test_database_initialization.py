"""Tests for database initialization during application startup."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from app.core.config import DEFAULT_SETTINGS
from app.main import _configure_application

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def test_configure_application_initializes_database(monkeypatch: MonkeyPatch) -> None:
    """The application configuration routine should initialize the database."""

    configure_logging = MagicMock()
    init_db = MagicMock()
    ensure_default_settings = MagicMock()
    refresh_cache = MagicMock()
    logger = MagicMock()

    monkeypatch.setattr("app.main.configure_logging", configure_logging)
    monkeypatch.setattr("app.main.init_db", init_db)
    monkeypatch.setattr("app.main.ensure_default_settings", ensure_default_settings)
    monkeypatch.setattr("app.main.activity_manager.refresh_cache", refresh_cache)
    monkeypatch.setattr("app.main.logger", logger)

    config = SimpleNamespace(logging=SimpleNamespace(level="info"))

    _configure_application(config)

    configure_logging.assert_called_once_with("info")
    init_db.assert_called_once_with()
    ensure_default_settings.assert_called_once_with(DEFAULT_SETTINGS)
    refresh_cache.assert_called_once_with()
    logger.info.assert_called_once_with("Database initialised")
