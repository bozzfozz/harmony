import pytest

from app.config import (
    DEFAULT_DB_URL_DEV,
    DEFAULT_DB_URL_PROD,
    DEFAULT_DB_URL_TEST,
    load_config,
    override_runtime_env,
    resolve_default_database_url,
)
from app.errors import ValidationAppError


def test_default_database_url_for_dev(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    override_runtime_env(None)
    config = load_config()
    assert config.database.url == DEFAULT_DB_URL_DEV


def test_default_database_url_for_prod(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "prod")
    override_runtime_env(None)
    config = load_config()
    assert config.database.url == DEFAULT_DB_URL_PROD


def test_default_database_url_for_test(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    override_runtime_env(None)
    config = load_config()
    assert config.database.url == DEFAULT_DB_URL_TEST


def test_database_url_rejects_non_sqlite(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:4444/harmony")
    override_runtime_env(None)
    with pytest.raises(ValidationAppError):
        load_config()


def test_resolve_default_database_url_dev_profile():
    assert resolve_default_database_url({}) == DEFAULT_DB_URL_DEV


def test_resolve_default_database_url_prod_profile():
    env = {"APP_ENV": "prod"}
    assert resolve_default_database_url(env) == DEFAULT_DB_URL_PROD


def test_resolve_default_database_url_pytest_flag():
    env = {"PYTEST_CURRENT_TEST": "tests::sample"}
    assert resolve_default_database_url(env) == DEFAULT_DB_URL_TEST


def test_resolve_default_database_url_unknown_value_defaults_to_dev():
    env = {"APP_ENV": "mystery"}
    assert resolve_default_database_url(env) == DEFAULT_DB_URL_DEV
