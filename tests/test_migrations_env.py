import pytest

pytest.importorskip("alembic", reason="alembic is required for migration environment tests")

from alembic.config import Config

from app.errors import ValidationAppError
from app.migrations import env


def test_get_database_url_prefers_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ALEMBIC_DATABASE_URL",
        "postgresql+psycopg://user:pass@db:5432/env",
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@db:5432/app")

    config = Config()
    config.set_main_option("sqlalchemy.url", "postgresql+psycopg://user:pass@db:5432/config")

    assert env.get_database_url(config) == ("postgresql+psycopg://user:pass@db:5432/env")


def test_get_database_url_requires_postgres_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "sqlite:///override.db")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    config = Config()

    with pytest.raises(ValidationAppError):
        env.get_database_url(config)


def test_get_database_url_prefers_config_override() -> None:
    config = Config()
    config.set_main_option("sqlalchemy.url", "postgresql+psycopg://user:pass@db:5432/override")

    assert env.get_database_url(config) == "postgresql+psycopg://user:pass@db:5432/override"


def test_get_database_url_requires_postgres_override() -> None:
    config = Config()
    non_postgres_scheme = "".join(["s", "qlite"])
    config.set_main_option("sqlalchemy.url", f"{non_postgres_scheme}:///override.db")

    with pytest.raises(ValidationAppError):
        env.get_database_url(config)


def test_get_database_url_requires_postgres(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://db/test")
    config = Config()
    config.set_main_option("sqlalchemy.url", "")

    with pytest.raises(ValidationAppError):
        env.get_database_url(config)
