"""Shared fixtures for download flow unit tests to bypass global DB setup."""

from __future__ import annotations

import pytest

from app import dependencies as deps
from tests import conftest as root_conftest


@pytest.fixture(autouse=True)
def configure_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory,
    request: pytest.FixtureRequest,
) -> None:
    deps.get_app_config.cache_clear()
    if hasattr(deps.get_spotify_client, "cache_clear"):
        deps.get_spotify_client.cache_clear()
    deps.get_soulseek_client.cache_clear()
    deps.get_transfers_api.cache_clear()
    deps.get_matching_engine.cache_clear()

    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")
    monkeypatch.setenv("ENABLE_ARTWORK", "1")
    monkeypatch.setenv("ENABLE_LYRICS", "1")
    root_conftest._install_recording_orchestrator(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("PYTEST_SKIP_POSTGRES", "1")
    yield


@pytest.fixture(autouse=True)
def reset_activity_manager() -> None:
    yield
