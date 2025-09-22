import asyncio
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import importlib


beets_router = importlib.import_module("app.routers.beets_router")


def test_import_music_runs_in_threadpool(monkeypatch):
    called = {}
    fake_result = SimpleNamespace(returncode=0, stdout="imported", stderr="")

    async def fake_run_in_threadpool(func, *args, **kwargs):
        called["func"] = func
        called["args"] = args
        called["kwargs"] = kwargs
        return fake_result

    monkeypatch.setattr(beets_router, "run_in_threadpool", fake_run_in_threadpool)

    response = asyncio.run(beets_router.import_music("/music/path"))

    assert called["func"] is subprocess.run
    assert called["args"] == (["beet", "import", "/music/path"],)
    assert called["kwargs"] == {
        "capture_output": True,
        "text": True,
        "check": False,
    }
    assert response == {"status": "success", "output": "imported"}


def test_import_music_failed_import_raises(monkeypatch):
    error_result = SimpleNamespace(returncode=1, stdout="", stderr="boom")

    async def fake_run_in_threadpool(*_args, **_kwargs):
        return error_result

    monkeypatch.setattr(beets_router, "run_in_threadpool", fake_run_in_threadpool)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(beets_router.import_music("/music/path"))

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "boom"
