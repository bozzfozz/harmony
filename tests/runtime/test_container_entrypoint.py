from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.config import DEFAULT_DB_URL_PROD, DEFAULT_DB_URL_TEST
from app.runtime import container_entrypoint


class ExecIntercept(RuntimeError):
    def __init__(self, command: list[str]) -> None:
        super().__init__("exec intercepted")
        self.command = command


def test_resolve_umask_parses_octal() -> None:
    assert container_entrypoint.resolve_umask("022") == 0o22


def test_resolve_umask_invalid_raises() -> None:
    with pytest.raises(container_entrypoint.BootstrapError):
        container_entrypoint.resolve_umask("invalid")


def test_ensure_directory_creates_and_verifies(tmp_path: Path) -> None:
    path = tmp_path / "downloads"
    result = container_entrypoint.ensure_directory(
        str(path),
        name="downloads",
        uid=os.getuid(),
        gid=os.getgid(),
        umask_value=0o022,
    )
    assert result == path.resolve()
    assert path.is_dir()


def test_ensure_directory_rejects_file(tmp_path: Path) -> None:
    path = tmp_path / "conflict"
    path.touch()
    assert path.is_file()
    assert not path.is_dir()
    with pytest.raises(container_entrypoint.BootstrapError):
        container_entrypoint.ensure_directory(
            str(path),
            name="downloads",
            uid=os.getuid(),
            gid=os.getgid(),
            umask_value=None,
        )


def test_ensure_sqlite_database_creates_file(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "harmony.db"
    url = f"sqlite+aiosqlite:///{db_path}"  # absolute path ensures direct resolution
    container_entrypoint.ensure_sqlite_database(url)
    assert db_path.exists()


def test_ensure_sqlite_database_logs_ready(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = (tmp_path / "data" / "harmony.db").resolve()
    url = f"sqlite+aiosqlite:///{db_path}"  # absolute path ensures direct resolution
    container_entrypoint.ensure_sqlite_database(url)
    captured = capsys.readouterr()
    ready_line = next(
        line for line in captured.out.splitlines() if "sqlite.bootstrap.ready" in line
    )
    payload = json.loads(ready_line.split(" ", 1)[1])
    assert payload["event"] == "sqlite.bootstrap.ready"
    assert payload["database_path"] == str(db_path)


@pytest.mark.parametrize("url", ["postgresql://localhost/db"])
def test_ensure_sqlite_database_invalid(url: str) -> None:
    with pytest.raises(container_entrypoint.BootstrapError):
        container_entrypoint.ensure_sqlite_database(url)


def test_ensure_sqlite_database_permission_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = (tmp_path / "data" / "harmony.db").resolve()
    url = f"sqlite+aiosqlite:///{db_path}"
    parent = db_path.parent

    original_access = container_entrypoint.os.access

    def fake_access(path: os.PathLike[str] | str, mode: int) -> bool:  # type: ignore[override]
        if Path(path).resolve() == parent and mode == os.W_OK | os.X_OK:
            return False
        return original_access(path, mode)

    monkeypatch.setattr(container_entrypoint.os, "access", fake_access)

    with pytest.raises(container_entrypoint.BootstrapError):
        container_entrypoint.ensure_sqlite_database(url)

    captured = capsys.readouterr()
    error_line = next(
        line for line in captured.err.splitlines() if "sqlite.bootstrap.parent_not_writable" in line
    )
    payload = json.loads(error_line.split(" ", 1)[1])
    assert payload["event"] == "sqlite.bootstrap.parent_not_writable"
    assert payload["parent"] == str(parent)


def test_combine_extra_args_removes_prefixed_invocation() -> None:
    assert container_entrypoint.combine_extra_args(
        ["python", "-m", "uvicorn", "--reload"],
        None,
    ) == ["--reload"]


def test_sanitize_extra_args_rejects_positional() -> None:
    with pytest.raises(container_entrypoint.EntrypointError):
        container_entrypoint.sanitize_extra_args(["module:app"])


def test_build_uvicorn_command_includes_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_entrypoint.sys, "executable", "/usr/bin/python")
    command = container_entrypoint.build_uvicorn_command(8080, "app.main:app", ["--reload"])
    assert command[:4] == ["/usr/bin/python", "-m", "uvicorn", "app.main:app"]
    assert command[-1] == "--reload"


def test_launch_application_executes_uvicorn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = container_entrypoint.BootstrapState(target_uid=os.getuid(), target_gid=os.getgid())
    env = {
        "UVICORN_EXTRA_ARGS": "--reload",
        "APP_MODULE": "app.main:app",
        "PYTHONPATH": str(tmp_path),
        "APP_LIVE_PATH": "/health",
    }
    monkeypatch.setattr(container_entrypoint, "resolve_app_port", lambda: 9000)
    monkeypatch.setattr(container_entrypoint.os, "getcwd", lambda: str(tmp_path))

    def fake_execvp(cmd: str, argv: list[str]) -> None:
        raise ExecIntercept(argv)

    monkeypatch.setattr(container_entrypoint.os, "execvp", fake_execvp)
    with pytest.raises(ExecIntercept) as exc:
        container_entrypoint.launch_application(["--workers", "2"], env, state)
    assert exc.value.command[2] == "uvicorn"
    assert "--reload" in exc.value.command
    assert env["APP_PORT"] == "9000"


def test_bootstrap_environment_sets_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads = tmp_path / "downloads"
    music = tmp_path / "music"
    env: dict[str, str] = {
        "DOWNLOADS_DIR": str(downloads),
        "MUSIC_DIR": str(music),
        "PUID": str(os.getuid()),
        "PGID": str(os.getgid()),
        "PYTEST_CURRENT_TEST": "tests::bootstrap",
    }
    state = container_entrypoint.bootstrap_environment(env)
    assert state.target_uid == os.getuid()
    assert env["DATABASE_URL"].startswith("sqlite+aiosqlite")
    assert downloads.exists()
    assert music.exists()


def test_ensure_database_url_uses_profile_default() -> None:
    env: dict[str, str] = {"APP_ENV": "prod"}
    result = container_entrypoint.ensure_database_url(env)
    assert result == DEFAULT_DB_URL_PROD
    assert env["DATABASE_URL"] == DEFAULT_DB_URL_PROD


def test_ensure_database_url_honours_pytest_flag() -> None:
    env: dict[str, str] = {"PYTEST_CURRENT_TEST": "tests::ensure"}
    result = container_entrypoint.ensure_database_url(env)
    assert result == DEFAULT_DB_URL_TEST
    assert env["DATABASE_URL"] == DEFAULT_DB_URL_TEST


def test_ensure_database_url_preserves_existing_value() -> None:
    custom = "sqlite+aiosqlite:///custom.db"
    env: dict[str, str] = {"DATABASE_URL": custom, "APP_ENV": "dev"}
    result = container_entrypoint.ensure_database_url(env)
    assert result == custom
    assert env["DATABASE_URL"] == custom


def test_drop_privileges_rejects_without_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_entrypoint.os, "getuid", lambda: 1001)
    monkeypatch.setattr(container_entrypoint.os, "getgid", lambda: 1001)
    with pytest.raises(container_entrypoint.EntrypointError):
        container_entrypoint.drop_privileges(1000, 1000)
