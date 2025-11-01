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


def test_default_oauth_state_dir_reexport() -> None:
    """The OAuth state directory constant should be available via ``app.config``."""

    from app.config import DEFAULT_OAUTH_STATE_DIR
    from app.runtime.paths import CONFIG_DIR

    assert Path(DEFAULT_OAUTH_STATE_DIR) == CONFIG_DIR / "runtime" / "oauth_state"
