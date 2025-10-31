from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import preflight_volume_check as pvc


def test_ensure_directories_creates_and_sets_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"

    ownership_calls: list[tuple[Path, int, int]] = []
    writable_calls: list[tuple[Path, int, int]] = []

    def fake_apply_ownership(path: Path, puid: int, pgid: int) -> None:
        ownership_calls.append((path, puid, pgid))

    def fake_check_writable(path: Path, puid: int, pgid: int) -> bool:
        writable_calls.append((path, puid, pgid))
        return True

    monkeypatch.setattr(pvc, "_apply_ownership", fake_apply_ownership)
    monkeypatch.setattr(pvc, "_check_writable", fake_check_writable)

    pvc.ensure_directories(
        config_dir=config_dir,
        downloads_dir=downloads_dir,
        music_dir=music_dir,
        puid=1234,
        pgid=4321,
    )

    expected_paths = [config_dir.resolve(), downloads_dir.resolve(), music_dir.resolve()]

    for directory in expected_paths:
        assert directory.is_dir()

    assert ownership_calls == [(path, 1234, 4321) for path in expected_paths]
    assert writable_calls == [(path, 1234, 4321) for path in expected_paths]


def test_ensure_directories_raises_when_directory_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"

    original_mkdir = pvc.Path.mkdir

    monkeypatch.setattr(pvc, "_check_writable", lambda *args, **kwargs: True)

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
