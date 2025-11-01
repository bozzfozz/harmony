from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest

from app.config.core import override_runtime_env
from app.core.soulseek_client import SoulseekClient
from app.orchestrator.handlers import SyncHandlerDeps
from app.runtime.paths import MUSIC_DIR
from app.workers.sync_worker import SyncWorker


@pytest.fixture(autouse=True)
def reset_runtime_env() -> None:
    override_runtime_env(None)
    yield
    override_runtime_env(None)


def _mock_soulseek_client() -> SoulseekClient:
    return cast(SoulseekClient, Mock(spec=SoulseekClient))


def test_music_dir_defaults_to_runtime_constant() -> None:
    override_runtime_env({})
    expected = MUSIC_DIR.expanduser()

    worker = SyncWorker(_mock_soulseek_client())
    deps = SyncHandlerDeps(soulseek_client=_mock_soulseek_client())

    assert worker._music_dir == expected
    assert deps.music_dir == expected


def test_music_dir_respects_env_override(tmp_path: Path) -> None:
    custom_dir = tmp_path / "library"
    custom_dir.mkdir()
    override_runtime_env({"MUSIC_DIR": str(custom_dir)})

    worker = SyncWorker(_mock_soulseek_client())
    deps = SyncHandlerDeps(soulseek_client=_mock_soulseek_client())

    assert worker._music_dir == custom_dir
    assert deps.music_dir == custom_dir


def test_music_dir_empty_env_falls_back_to_runtime_constant() -> None:
    override_runtime_env({"MUSIC_DIR": ""})
    expected = MUSIC_DIR.expanduser()

    worker = SyncWorker(_mock_soulseek_client())
    deps = SyncHandlerDeps(soulseek_client=_mock_soulseek_client())

    assert worker._music_dir == expected
    assert deps.music_dir == expected
