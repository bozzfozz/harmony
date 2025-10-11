from app.config import (
    DEFAULT_DB_URL_DEV,
    DEFAULT_DB_URL_PROD,
    DEFAULT_DB_URL_TEST,
    load_config,
    override_runtime_env,
)


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
