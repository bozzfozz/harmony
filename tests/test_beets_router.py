import asyncio
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import beets_router


def test_import_music_runs_in_threadpool(monkeypatch):
    async def runner():
        called = {}

        async def fake_run_in_threadpool(func, *args, **kwargs):
            called["func"] = func
            called["args"] = args
            called["kwargs"] = kwargs
            return SimpleNamespace(stdout="imported")

        monkeypatch.setattr(beets_router, "run_in_threadpool", fake_run_in_threadpool)
        monkeypatch.setattr(
            beets_router.config_manager,
            "get_beets_env",
            lambda: {"BEETSCONFIG": "/tmp/config"},
        )

        request = beets_router.ImportRequest(path="/music/path", quiet=False, autotag=False)
        response = await beets_router.import_music(request)

        assert called["func"] is subprocess.run
        assert called["args"] == (["beet", "import", "/music/path"],)
        assert called["kwargs"]["capture_output"] is True
        assert called["kwargs"]["text"] is True
        assert called["kwargs"]["check"] is True
        assert called["kwargs"]["env"]["BEETSCONFIG"] == "/tmp/config"
        assert response.success is True
        assert response.message == "imported"

    asyncio.run(runner())


def test_import_music_includes_flags(monkeypatch):
    async def runner():
        captured_args = {}

        async def fake_run_in_threadpool(func, *args, **kwargs):
            captured_args["args"] = args
            return SimpleNamespace(stdout="")

        monkeypatch.setattr(beets_router, "run_in_threadpool", fake_run_in_threadpool)
        monkeypatch.setattr(beets_router.config_manager, "get_beets_env", lambda: {})

        request = beets_router.ImportRequest(path="/music/path")
        await beets_router.import_music(request)

        assert captured_args["args"] == (["beet", "import", "-q", "-A", "/music/path"],)

    asyncio.run(runner())


def test_run_beets_command_error(monkeypatch):
    async def runner():
        async def fake_run_in_threadpool(*_args, **_kwargs):
            raise subprocess.CalledProcessError(1, ["beet"], stderr="boom")

        monkeypatch.setattr(beets_router, "run_in_threadpool", fake_run_in_threadpool)
        monkeypatch.setattr(beets_router.config_manager, "get_beets_env", lambda: {})

        with pytest.raises(HTTPException) as exc_info:
            await beets_router._run_beets_command(["import"])

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Beets error: boom"

    asyncio.run(runner())


def test_list_albums_and_tracks(monkeypatch):
    async def runner():
        responses = {
            ("ls", "-a"): "Album One\nAlbum Two\n",
            ("ls", "-f", "$title"): "Track One\nTrack Two\n",
        }

        async def fake_run_beets_command(args):
            return responses[tuple(args)]

        monkeypatch.setattr(beets_router, "_run_beets_command", fake_run_beets_command)

        albums = await beets_router.list_albums()
        tracks = await beets_router.list_tracks()

        assert albums.albums == ["Album One", "Album Two"]
        assert tracks.tracks == ["Track One", "Track Two"]

    asyncio.run(runner())
