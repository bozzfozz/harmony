from __future__ import annotations

from pathlib import Path
import sys
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

    import importlib.util

    module_path = Path(__file__).resolve().parents[1] / "app" / "config.py"
    spec = importlib.util.spec_from_file_location("app_config_entrypoint", module_path)
    config_module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = config_module
    sys.modules["app.config"] = config_module
    spec.loader.exec_module(config_module)
    config_module.database = db_config

    import app.runtime.container_entrypoint as entrypoint  # noqa: WPS433
    return entrypoint


def test_ensure_database_url_overrides_env(monkeypatch, tmp_path):
    entrypoint = _install_sqlalchemy_stubs(monkeypatch)
    fake_db = tmp_path / "harmony.db"
    fixed_url = f"sqlite+aiosqlite:///{fake_db}"

    monkeypatch.setattr(db_config, "HARMONY_DATABASE_FILE", fake_db, raising=False)
    monkeypatch.setattr(db_config, "HARMONY_DATABASE_URL", fixed_url, raising=False)
    monkeypatch.setattr(db_config, "get_database_url", lambda: fixed_url, raising=False)
    monkeypatch.setattr(entrypoint, "get_database_url", lambda: fixed_url, raising=False)
    monkeypatch.setattr(entrypoint, "log_info", lambda *args, **kwargs: None)

    env: dict[str, str] = {"DATABASE_URL": "sqlite:///override.db"}

    resolved = entrypoint.ensure_database_url(env)

    assert resolved == fixed_url
    assert env["DATABASE_URL"] == fixed_url
