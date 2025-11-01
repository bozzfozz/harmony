from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.config.database as db_config


def _install_sqlalchemy_stubs(monkeypatch):
    sqlalchemy_module = types.ModuleType("sqlalchemy")
    sqlalchemy_module.create_engine = lambda *args, **kwargs: None
    sqlalchemy_module.text = lambda *args, **kwargs: None

    def _make_url(url: str):
        class _URL:
            def __init__(self, raw: str) -> None:
                self.drivername = "sqlite"
                self.database = raw

            def render_as_string(self, *, hide_password: bool = False) -> str:  # noqa: ARG002
                return url

            def set(self, *, drivername: str | None = None):  # noqa: ARG002
                return _make_url(url)

        return _URL(url)

    engine_module = types.ModuleType("sqlalchemy.engine")
    engine_module.make_url = _make_url

    exc_module = types.ModuleType("sqlalchemy.exc")

    class _DummyArgumentError(Exception):
        pass

    exc_module.ArgumentError = _DummyArgumentError
    exc_module.SQLAlchemyError = _DummyArgumentError

    sqlalchemy_module.engine = engine_module
    sqlalchemy_module.exc = exc_module

    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy_module)
    monkeypatch.setitem(sys.modules, "sqlalchemy.engine", engine_module)
    monkeypatch.setitem(sys.modules, "sqlalchemy.exc", exc_module)


def _load_config_module():
    module_path = Path(__file__).resolve().parents[1] / "app" / "config.py"
    spec = importlib.util.spec_from_file_location("app_config_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    sys.modules["app.config"] = module
    spec.loader.exec_module(module)
    module.database = db_config
    return module


def _dummy_settings() -> object:
    return SimpleNamespace(
        orchestrator=SimpleNamespace(
            workers_enabled=True,
            global_concurrency=1,
            poll_interval_ms=100,
            poll_interval_max_ms=200,
            visibility_timeout_s=30,
        ),
        external=SimpleNamespace(
            timeout_ms=1000,
            retry_max=1,
            backoff_base_ms=100,
            jitter_pct=0.0,
        ),
        watchlist_timer=SimpleNamespace(enabled=True, interval_s=60.0),
        hdm=SimpleNamespace(downloads_dir="/tmp", music_dir="/tmp"),
        provider_profiles={},
        retry_policy=SimpleNamespace(max_attempts=1, base_seconds=1.0, jitter_pct=0.0),
    )


def test_load_config_uses_fixed_database_url(monkeypatch, tmp_path):
    _install_sqlalchemy_stubs(monkeypatch)
    config = _load_config_module()
    monkeypatch.setattr(config, "DEFAULT_DATABASE_URL_HINT", db_config.HARMONY_DATABASE_URL, raising=False)
    monkeypatch.setattr(config, "get_database_url", db_config.get_database_url, raising=False)
    monkeypatch.setattr(config, "_load_settings_from_db", lambda *args, **kwargs: {})
    monkeypatch.setattr(config, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(config.Settings, "load", classmethod(lambda cls, env=None: _dummy_settings()))

    runtime_env = {"APP_ENV": "prod", "DATABASE_URL": "sqlite:///ignored.db"}

    app_config = config.load_config(runtime_env)

    assert app_config.database.url == db_config.HARMONY_DATABASE_URL
