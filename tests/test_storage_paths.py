import pytest

from app.runtime import paths


def test_bootstrap_storage_creates_directories_and_db(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    sqlite_path = config_dir / "harmony.db"
    sqlite_url = f"sqlite:///{sqlite_path}"

    monkeypatch.setattr(paths, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(paths, "DOWNLOADS_DIR", downloads_dir)
    monkeypatch.setattr(paths, "MUSIC_DIR", music_dir)
    monkeypatch.setattr(paths, "SQLITE_DB_PATH", sqlite_path)
    monkeypatch.setattr(paths, "SQLITE_DATABASE_URL", sqlite_url, raising=False)

    paths.bootstrap_storage()

    assert config_dir.is_dir()
    assert downloads_dir.is_dir()
    assert music_dir.is_dir()
    assert sqlite_path.exists()


def test_validate_permissions_rejects_non_directory(tmp_path) -> None:
    file_path = tmp_path / "not_a_dir"
    file_path.write_text("content", encoding="utf-8")

    with pytest.raises(paths.StorageError):
        paths.validate_permissions(file_path)
