import pytest

pytest.importorskip("alembic", reason="alembic is required for migration environment tests")

from alembic.config import Config

from app.migrations import env
from app.errors import ValidationAppError


def test_get_database_url_prefers_config_override() -> None:
    config = Config()
    config.set_main_option("sqlalchemy.url", "sqlite:///override.db")

    assert env.get_database_url(config) == "sqlite:///override.db"


def test_get_database_url_requires_postgres(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test-env.db")
    config = Config()
    config.set_main_option("sqlalchemy.url", "")

    with pytest.raises(ValidationAppError):
        env.get_database_url(config)
