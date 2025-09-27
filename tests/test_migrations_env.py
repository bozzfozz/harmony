import pytest

pytest.importorskip("alembic", reason="alembic is required for migration environment tests")

from alembic.config import Config

from app.migrations import env


def test_get_database_url_prefers_config_override() -> None:
    config = Config()
    config.set_main_option("sqlalchemy.url", "sqlite:///override.db")

    assert env.get_database_url(config) == "sqlite:///override.db"


def test_get_database_url_falls_back_to_app_config(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test-env.db")
    config = Config()
    config.set_main_option("sqlalchemy.url", "")

    resolved = env.get_database_url(config)

    assert resolved.endswith("test-env.db")
    assert resolved.startswith("sqlite")
