from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import preflight_volume_check as pvc


def test_ensure_directories_creates_and_sets_permissions(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"

    pvc.ensure_directories(
        config_dir=config_dir,
        downloads_dir=downloads_dir,
        music_dir=music_dir,
        puid=1234,
        pgid=4321,
    )

    for directory in (config_dir, downloads_dir, music_dir):
        assert directory.is_dir()
        metadata = directory.stat()
        assert metadata.st_uid == 1234
        assert metadata.st_gid == 4321


def test_ensure_directories_raises_when_directory_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"

    original_mkdir = pvc.Path.mkdir

    def fake_mkdir(self: Path, *args, **kwargs):
        if self == downloads_dir:
            raise PermissionError("read-only")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(pvc.Path, "mkdir", fake_mkdir)

    with pytest.raises(pvc.PreflightError) as excinfo:
        pvc.ensure_directories(
            config_dir=config_dir,
            downloads_dir=downloads_dir,
            music_dir=music_dir,
            puid=1000,
            pgid=1000,
        )

    assert "Unable to create downloads directory" in str(excinfo.value)


def test_ensure_directories_validates_writability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"

    pvc.ensure_directories(
        config_dir=config_dir,
        downloads_dir=downloads_dir,
        music_dir=music_dir,
        puid=1000,
        pgid=1000,
    )

    os.chmod(downloads_dir, 0o555)
    monkeypatch.setattr(pvc, "_is_root", lambda: False)

    with pytest.raises(pvc.PreflightError) as excinfo:
        pvc.ensure_directories(
            config_dir=config_dir,
            downloads_dir=downloads_dir,
            music_dir=music_dir,
            puid=1000,
            pgid=1000,
        )

    assert "Directory permissions reject" in str(excinfo.value)
