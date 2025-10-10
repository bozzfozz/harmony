from __future__ import annotations

import os
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_database


class _ReadyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:  # pragma: no cover - trivial
        try:
            self.request.recv(8)
        except OSError:
            return


class _ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _start_dummy_server() -> tuple[_ThreadedServer, threading.Thread]:
    server = _ThreadedServer(("127.0.0.1", 0), _ReadyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _build_env(
    tmp_path: Path, *, overrides: dict[str, str] | None = None
) -> tuple[dict[str, str], tuple[_ThreadedServer, threading.Thread]]:
    server, thread = _start_dummy_server()
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    oauth_state_dir = tmp_path / "oauth_state"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    music_dir.mkdir(parents=True, exist_ok=True)
    oauth_state_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "SPOTIFY_CLIENT_ID": "test-client",
            "SPOTIFY_CLIENT_SECRET": "test-secret",
            "OAUTH_SPLIT_MODE": "false",
            "DOWNLOADS_DIR": str(downloads_dir),
            "MUSIC_DIR": str(music_dir),
            "OAUTH_STATE_DIR": str(oauth_state_dir),
            "SLSKD_HOST": server.server_address[0],
            "SLSKD_PORT": str(server.server_address[1]),
            "HARMONY_API_KEY": "startup-guard",
            "HEALTH_READY_REQUIRE_DB": "false",
            "HARMONY_API_KEYS": "startup-guard",
        }
    )
    if overrides:
        env.update(overrides)
    return env, (server, thread)


def _run_selfcheck(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.ops.selfcheck", "--assert-startup"],
        env=env,
        capture_output=True,
        text=True,
    )


def _shutdown(server: _ThreadedServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=1)


def test_startup_guard_missing_env(tmp_path: Path) -> None:
    env, ctx = _build_env(tmp_path)
    server, thread = ctx
    try:
        env.pop("SPOTIFY_CLIENT_ID", None)
        result = _run_selfcheck(env)
    finally:
        _shutdown(server, thread)
    assert result.returncode == os.EX_CONFIG


def test_startup_guard_unwritable_downloads(tmp_path: Path) -> None:
    env, ctx = _build_env(tmp_path)
    server, thread = ctx
    bad_path = tmp_path / "bad-file"
    bad_path.write_text("not-a-dir")
    env["DOWNLOADS_DIR"] = str(bad_path)
    try:
        result = _run_selfcheck(env)
    finally:
        _shutdown(server, thread)
    assert result.returncode == os.EX_OSERR


def test_startup_guard_requires_oauth_state(tmp_path: Path) -> None:
    env, ctx = _build_env(tmp_path)
    server, thread = ctx
    env["OAUTH_SPLIT_MODE"] = "true"
    env.pop("OAUTH_STATE_DIR", None)
    try:
        result = _run_selfcheck(env)
    finally:
        _shutdown(server, thread)
    assert result.returncode == os.EX_CONFIG


def test_startup_guard_soulseek_unreachable(tmp_path: Path) -> None:
    env, ctx = _build_env(tmp_path)
    server, thread = ctx
    _shutdown(server, thread)
    env["SLSKD_PORT"] = "59999"
    result = _run_selfcheck(env)
    assert result.returncode == os.EX_UNAVAILABLE
