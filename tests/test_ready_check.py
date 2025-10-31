from pathlib import Path
import socketserver
import threading
from typing import Any

import pytest

from app.db import init_db, reset_engine_for_tests
from app.main import _ui_dependency_probe
from app.ops import selfcheck_ui
from app.ops.selfcheck import aggregate_ready
from app.services.health import DependencyStatus


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:  # pragma: no cover - used for readiness tests
        try:
            self.request.recv(8)
        except OSError:
            return


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


@pytest.mark.parametrize(
    ("variant", "expected_source", "base_url_key"),
    [
        pytest.param("legacy", "host_port", None, id="legacy-host-port"),
        pytest.param("base_url", "base_url", "SLSKD_BASE_URL", id="base-url"),
        pytest.param("legacy_alias", "base_url", "SLSKD_URL", id="legacy-base-url-alias"),
    ],
)
def test_ready_reports_database_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
    expected_source: str,
    base_url_key: str | None,
) -> None:
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    oauth_state_dir = tmp_path / "oauth_state"
    for directory in (downloads_dir, music_dir, oauth_state_dir):
        directory.mkdir(parents=True, exist_ok=True)

    db_file = tmp_path / "harmony.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    monkeypatch.setenv("APP_ENV", "dev")

    reset_engine_for_tests()
    init_db()

    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        runtime_env: dict[str, str] = {
            "SPOTIFY_CLIENT_ID": "client",
            "SPOTIFY_CLIENT_SECRET": "secret",
            "OAUTH_SPLIT_MODE": "false",
            "DOWNLOADS_DIR": str(downloads_dir),
            "MUSIC_DIR": str(music_dir),
            "OAUTH_STATE_DIR": str(oauth_state_dir),
            "HARMONY_API_KEY": "ready-key",
            "HEALTH_READY_REQUIRE_DB": "true",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_file}",
        }

        if variant == "legacy":
            runtime_env.update({"SLSKD_HOST": host, "SLSKD_PORT": str(port)})
        elif variant == "base_url":
            runtime_env["SLSKD_BASE_URL"] = f"http://{host}:{port}"
        else:
            runtime_env["SLSKD_URL"] = f"http://{host}:{port}"

        report = aggregate_ready(runtime_env=runtime_env)
        assert report.ok

        database_check = report.checks["database"]
        assert database_check["mode"] == "file"
        assert database_check["exists"] is True
        assert database_check["writable"] is True

        soulseekd_check = report.checks["soulseekd"]
        assert soulseekd_check["reachable"] is True
        assert soulseekd_check["host"] == host
        assert soulseekd_check["port"] == port
        assert soulseekd_check["source"] == expected_source
        if base_url_key is None:
            assert soulseekd_check["base_url"] is None
            assert soulseekd_check["base_url_key"] is None
        else:
            assert soulseekd_check["base_url_key"] == base_url_key
            assert soulseekd_check["base_url"] == f"http://{host}:{port}"

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
        reset_engine_for_tests()


def _base_ready_env(
    *,
    downloads_dir: Path,
    music_dir: Path,
    idempotency_path: Path,
    create_database: bool = True,
) -> dict[str, str]:
    downloads_dir.mkdir(parents=True, exist_ok=True)
    music_dir.mkdir(parents=True, exist_ok=True)
    idempotency_path.parent.mkdir(parents=True, exist_ok=True)
    database_path = downloads_dir / "ready.db"
    if create_database:
        database_path.touch()
    return {
        "SPOTIFY_CLIENT_ID": "client",
        "SPOTIFY_CLIENT_SECRET": "secret",
        "OAUTH_SPLIT_MODE": "false",
        "DOWNLOADS_DIR": str(downloads_dir),
        "MUSIC_DIR": str(music_dir),
        "OAUTH_STATE_DIR": str(downloads_dir / "oauth"),
        "HARMONY_API_KEY": "ready-key",
        "SLSKD_HOST": "127.0.0.1",
        "SLSKD_PORT": "5030",
        "DATABASE_URL": f"sqlite+aiosqlite:///{database_path}",
        "IDEMPOTENCY_SQLITE_PATH": str(idempotency_path),
    }


def test_ready_reports_idempotency_sqlite(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    idempotency_db = tmp_path / "state" / "idempotency.db"
    runtime_env = _base_ready_env(
        downloads_dir=downloads_dir,
        music_dir=music_dir,
        idempotency_path=idempotency_db,
    )
    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        runtime_env["SLSKD_BASE_URL"] = f"http://{host}:{port}"
        runtime_env.pop("SLSKD_HOST", None)
        runtime_env.pop("SLSKD_PORT", None)
        report = aggregate_ready(runtime_env=runtime_env)
        assert report.ok
        idempotency_check = report.checks["idempotency"]
        assert idempotency_check["status"] == "ok"
        assert idempotency_check["backend"] == "sqlite"
        assert idempotency_check["path"] == str(idempotency_db)
        assert idempotency_check.get("inserted") is True
        assert idempotency_db.exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_ready_creates_missing_sqlite_database(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    idempotency_db = tmp_path / "state" / "idempotency.db"
    runtime_env = _base_ready_env(
        downloads_dir=downloads_dir,
        music_dir=music_dir,
        idempotency_path=idempotency_db,
        create_database=False,
    )
    database_path = downloads_dir / "ready.db"
    assert not database_path.exists()

    runtime_env["INTEGRATIONS_ENABLED"] = "spotify"

    report = aggregate_ready(runtime_env=runtime_env)

    assert report.ok
    database_check = report.checks["database"]
    assert database_check["mode"] == "file"
    assert database_check["exists"] is True
    assert database_check["writable"] is True
    assert database_path.exists()


def test_ready_reports_invalid_idempotency_backend(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    idempotency_db = tmp_path / "state" / "idempotency.db"
    runtime_env = _base_ready_env(
        downloads_dir=downloads_dir,
        music_dir=music_dir,
        idempotency_path=idempotency_db,
    )
    runtime_env["IDEMPOTENCY_BACKEND"] = "bogus"
    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        runtime_env["SLSKD_BASE_URL"] = f"http://{host}:{port}"
        runtime_env.pop("SLSKD_HOST", None)
        runtime_env.pop("SLSKD_PORT", None)
        report = aggregate_ready(runtime_env=runtime_env)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
    assert report.ok is False
    idempotency_issue = next(issue for issue in report.issues if issue.component == "idempotency")
    assert "Invalid idempotency configuration" in idempotency_issue.message


def _create_ui_root(base_dir: Path) -> Path:
    templates_root = base_dir / "templates"
    static_root = base_dir / "static"
    for relative in selfcheck_ui.REQUIRED_TEMPLATE_FILES:
        target = templates_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("template", encoding="utf-8")
    for relative in selfcheck_ui.REQUIRED_STATIC_ASSETS:
        target = static_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("asset", encoding="utf-8")
    return base_dir


def test_ready_skips_soulseekd_when_integration_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    idempotency_db = tmp_path / "state" / "idempotency.db"
    runtime_env = _base_ready_env(
        downloads_dir=downloads_dir,
        music_dir=music_dir,
        idempotency_path=idempotency_db,
    )
    runtime_env["INTEGRATIONS_ENABLED"] = "spotify"
    # Ensure reachability probe would fail if executed.
    monkeypatch.setattr("app.ops.selfcheck.check_tcp_reachable", lambda *_, **__: False)

    report = aggregate_ready(runtime_env=runtime_env)
    assert report.ok

    soulseekd_check = report.checks["soulseekd"]
    assert soulseekd_check["enabled"] is False
    assert soulseekd_check["status"] == "skipped"
    assert soulseekd_check["reachable"] is None
    assert soulseekd_check.get("reason") == "integration_disabled"


def test_ready_reports_soulseekd_unreachable_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    idempotency_db = tmp_path / "state" / "idempotency.db"
    runtime_env = _base_ready_env(
        downloads_dir=downloads_dir,
        music_dir=music_dir,
        idempotency_path=idempotency_db,
    )
    monkeypatch.setattr("app.ops.selfcheck.check_tcp_reachable", lambda *_, **__: False)

    report = aggregate_ready(runtime_env=runtime_env)
    assert report.ok is False

    issue = next(issue for issue in report.issues if issue.component == "soulseekd")
    assert "Unable to reach Soulseekd" in issue.message


@pytest.mark.parametrize(
    ("missing", "category"),
    [
        pytest.param("pages/login.j2", "templates", id="missing-template"),
        pytest.param("css/app.css", "static", id="missing-static"),
    ],
)
def test_ready_reports_missing_ui_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
    category: str,
) -> None:
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    idempotency_db = tmp_path / "state" / "idempotency.db"
    runtime_env = _base_ready_env(
        downloads_dir=downloads_dir,
        music_dir=music_dir,
        idempotency_path=idempotency_db,
    )

    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ui_root = _create_ui_root(tmp_path / "ui")

    try:
        host, port = server.server_address
        runtime_env["SLSKD_HOST"] = host
        runtime_env["SLSKD_PORT"] = str(port)

        if category == "templates":
            target = ui_root / "templates" / missing
        else:
            target = ui_root / "static" / missing
        if target.exists():
            target.unlink()

        monkeypatch.setattr(selfcheck_ui, "UI_ROOT", ui_root)

        report = aggregate_ready(runtime_env=runtime_env)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert report.ok is False
    ui_check = report.checks["ui"]
    assert ui_check["status"] == "fail"
    templates_info = ui_check["templates"]
    static_info = ui_check["static"]
    assert not templates_info["unreadable"]
    assert not static_info["unreadable"]
    if category == "templates":
        assert missing in templates_info["missing"]
    else:
        assert missing in static_info["missing"]

    ui_issue = next(issue for issue in report.issues if issue.component == "ui")
    issue_details = ui_issue.details
    if category == "templates":
        assert missing in issue_details["templates"]["missing"]
    else:
        assert missing in issue_details["static"]["missing"]


def test_ready_reports_unreadable_ui_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    idempotency_db = tmp_path / "state" / "idempotency.db"
    runtime_env = _base_ready_env(
        downloads_dir=downloads_dir,
        music_dir=music_dir,
        idempotency_path=idempotency_db,
    )

    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ui_root = _create_ui_root(tmp_path / "ui")

    target_relative = selfcheck_ui.REQUIRED_TEMPLATE_FILES[0]
    target = ui_root / "templates" / target_relative

    original_open = Path.open

    def _blocked_open(self: Path, *args: Any, **kwargs: Any):
        if self == target:
            raise PermissionError("denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _blocked_open)

    try:
        host, port = server.server_address
        runtime_env["SLSKD_HOST"] = host
        runtime_env["SLSKD_PORT"] = str(port)

        monkeypatch.setattr(selfcheck_ui, "UI_ROOT", ui_root)

        report = aggregate_ready(runtime_env=runtime_env)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert report.ok is False
    ui_check = report.checks["ui"]
    assert target_relative in ui_check["templates"]["unreadable"]

    ui_issue = next(issue for issue in report.issues if issue.component == "ui")
    assert target_relative in ui_issue.details["templates"]["unreadable"]


def test_ui_dependency_probe_reports_degraded(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    details = {
        "templates": {"missing": ["pages/login.j2"], "unreadable": []},
        "static": {"missing": [], "unreadable": ["css/app.css"]},
    }
    monkeypatch.setattr("app.main.probe_ui_artifacts", lambda: (False, details))

    with caplog.at_level("WARNING"):
        status = _ui_dependency_probe()

    assert status == DependencyStatus(ok=False, status="degraded")
    assert any(record.message == "UI assets readiness probe failed" for record in caplog.records)
