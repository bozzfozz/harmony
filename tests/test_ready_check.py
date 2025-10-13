from pathlib import Path
import socketserver
import threading

from app.db import init_db, reset_engine_for_tests
from app.ops.selfcheck import aggregate_ready


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:  # pragma: no cover - used for readiness tests
        try:
            self.request.recv(8)
        except OSError:
            return


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def test_ready_reports_database_file(tmp_path: Path, monkeypatch):
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
        runtime_env = {
            "SPOTIFY_CLIENT_ID": "client",
            "SPOTIFY_CLIENT_SECRET": "secret",
            "OAUTH_SPLIT_MODE": "false",
            "DOWNLOADS_DIR": str(downloads_dir),
            "MUSIC_DIR": str(music_dir),
            "OAUTH_STATE_DIR": str(oauth_state_dir),
            "SLSKD_HOST": host,
            "SLSKD_PORT": str(port),
            "HARMONY_API_KEY": "ready-key",
            "HEALTH_READY_REQUIRE_DB": "true",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_file}",
        }

        report = aggregate_ready(runtime_env=runtime_env)
        assert report.ok
        database_check = report.checks["database"]
        assert database_check["mode"] == "file"
        assert database_check["exists"] is True
        assert database_check["writable"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
        reset_engine_for_tests()
