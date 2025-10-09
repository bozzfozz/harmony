import pytest

pytest.importorskip("alembic", reason="alembic is required for migration environment tests")

from alembic.config import Config

from app.migrations import env
from app.errors import ValidationAppError


def test_get_database_url_prefers_config_override() -> None:
    config = Config()
    config.set_main_option(
        "sqlalchemy.url", "postgresql+psycopg://user:pass@db:5432/override"
    )

    assert (
        env.get_database_url(config)
        == "postgresql+psycopg://user:pass@db:5432/override"
    )


def test_get_database_url_requires_postgres_override() -> None:
    config = Config()
    legacy_file_scheme = "file+memory"
    config.set_main_option("sqlalchemy.url", f"{legacy_file_scheme}:///override.db")

    with pytest.raises(ValidationAppError):
        env.get_database_url(config)


def test_get_database_url_requires_postgres(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://db/test")
    config = Config()
    config.set_main_option("sqlalchemy.url", "")

    with pytest.raises(ValidationAppError):
        env.get_database_url(config)
