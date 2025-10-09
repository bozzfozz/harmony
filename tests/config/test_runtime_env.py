from __future__ import annotations

from pathlib import Path

import pytest

from app.config import (
    DEFAULT_DB_URL,
    get_runtime_env,
    load_config,
    load_runtime_env,
    override_runtime_env,
)


@pytest.fixture(autouse=True)
def reset_runtime_env() -> None:
    override_runtime_env(None)
    yield
    override_runtime_env(None)


def test_load_config_uses_code_defaults_without_env() -> None:
    config = load_config(runtime_env={})

    assert config.database.url == DEFAULT_DB_URL
    assert config.logging.level == "INFO"
    assert config.features.enable_admin_api is False
    assert config.security.require_auth is False


def test_load_runtime_env_merges_dotenv_and_env(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "HARMONY_LOG_LEVEL=DEBUG\nCACHE_ENABLED=false\n", encoding="utf-8"
    )

    runtime_env = load_runtime_env(
        env_file=env_file, base_env={"CACHE_ENABLED": "true"}
    )

    assert runtime_env["HARMONY_LOG_LEVEL"] == "DEBUG"
    assert runtime_env["CACHE_ENABLED"] == "true"
    # Values missing in both sources are absent rather than synthesised.
    assert "DATABASE_URL" not in runtime_env


def test_env_variables_override_dotenv_and_defaults(tmp_path: Path) -> None:
    env_file = tmp_path / "example.env"
    env_file.write_text(
        "\n".join(
            [
                "HARMONY_LOG_LEVEL=DEBUG",
                "FEATURE_ADMIN_API=1",
                "DATABASE_URL=postgresql+psycopg://envfile:harmony@localhost:5432/app",
            ]
        ),
        encoding="utf-8",
    )

    runtime_env = load_runtime_env(
        env_file=env_file,
        base_env={
            "HARMONY_LOG_LEVEL": "WARNING",
            "DATABASE_URL": "postgresql+psycopg://override:harmony@localhost:5432/app",
        },
    )
    override_runtime_env(runtime_env)

    config = load_config()

    assert config.logging.level == "WARNING"
    assert (
        config.database.url
        == "postgresql+psycopg://override:harmony@localhost:5432/app"
    )
    assert config.features.enable_admin_api is True

    # Cache is populated from load_runtime_env, repeated calls reuse cached mapping.
    assert get_runtime_env()["HARMONY_LOG_LEVEL"] == "WARNING"
