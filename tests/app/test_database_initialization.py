from __future__ import annotations

from dataclasses import replace
from typing import Iterator

import pytest

from app import dependencies as deps
from app.config import AppConfig, EnvironmentConfig, override_runtime_env
from app.main import _should_initialize_database


@pytest.fixture(autouse=True)
def _reset_runtime_env() -> Iterator[None]:
    override_runtime_env(None)
    deps.get_app_config.cache_clear()
    try:
        yield
    finally:
        override_runtime_env(None)
        deps.get_app_config.cache_clear()


@pytest.fixture(autouse=True)
def configure_environment() -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def reset_activity_manager() -> Iterator[None]:
    yield


def _make_test_environment(
    is_test: bool, base_profile: str, config: AppConfig
) -> EnvironmentConfig:
    profile = "test" if is_test else base_profile
    return replace(
        config.environment,
        profile=profile,
        is_dev=profile == "dev",
        is_test=is_test,
        is_staging=profile == "staging",
        is_prod=profile == "prod",
    )


def test_should_skip_database_initialisation_in_test_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HARMONY_INIT_DB", raising=False)
    config = deps.get_app_config()
    test_env = _make_test_environment(True, config.environment.profile, config)
    test_config = replace(config, environment=test_env)

    assert _should_initialize_database(test_config) is False


def test_override_allows_database_initialisation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARMONY_INIT_DB", "1")
    override_runtime_env(None)
    deps.get_app_config.cache_clear()
    config = deps.get_app_config()
    test_env = _make_test_environment(True, config.environment.profile, config)
    test_config = replace(config, environment=test_env)

    assert _should_initialize_database(test_config) is True


def test_override_can_disable_database_initialisation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARMONY_INIT_DB", "false")
    override_runtime_env(None)
    deps.get_app_config.cache_clear()
    config = deps.get_app_config()
    dev_env = _make_test_environment(False, "dev", config)
    dev_config = replace(config, environment=dev_env)

    assert _should_initialize_database(dev_config) is False
