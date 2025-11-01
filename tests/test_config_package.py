"""Regression tests for the :mod:`app.config` package facade."""

from __future__ import annotations

from pathlib import Path


def test_app_config_package_reexports(tmp_path: Path) -> None:
    """Ensure ``AppConfig`` and ``load_config`` can be imported from the package."""

    from app.config import AppConfig, load_config

    runtime_env = {
        "APP_ENV": "test",
        "DOWNLOADS_DIR": str(tmp_path / "downloads"),
        "MUSIC_DIR": str(tmp_path / "music"),
        "OAUTH_STATE_DIR": str(tmp_path / "oauth_state"),
        "PYTEST_CURRENT_TEST": "config-package-test",
    }

    config = load_config(runtime_env)

    assert isinstance(config, AppConfig)
    assert config.environment.is_test is True
