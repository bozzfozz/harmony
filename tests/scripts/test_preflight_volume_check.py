from pathlib import Path

import pytest

import scripts.preflight_volume_check as pvc


def test_ensure_directories_creates_and_sets_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Erwartung:
    - ensure_directories() legt config/downloads/music an.
    - Wendet Ownership an.
    - Prüft Schreibbarkeit.
    - Wirft KEIN PreflightError, wenn alles ok ist.

    Um CI-deterministisch zu bleiben:
    - _apply_ownership wird gemockt, damit kein echtes chown mit fremden UIDs/GIDs passiert.
    - _check_writable wird gemockt, um True zurückzugeben (also "alles schreibbar").
    """

    config_dir = tmp_path / "config"
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"

    def fake_apply_ownership(path: Path, puid: int, pgid: int) -> None:
        # simulate successful chown without root
        return None

    def fake_check_writable(path: Path, puid: int, pgid: int) -> bool:
        # pretend container user can write
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

    assert config_dir.is_dir()
    assert downloads_dir.is_dir()
    assert music_dir.is_dir()


def test_ensure_directories_raises_when_directory_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Erwartung:
    - Wenn mkdir() für downloads_dir scheitert (z.B. PermissionError),
      dann soll ensure_directories() einen PreflightError werfen,
      der "Unable to create downloads directory" enthält.
    - Die Fehlermeldung muss den problematischen Pfad und die ursprüngliche Exception enthalten.

    Um CI-deterministisch zu bleiben:
    - Wir mocken _apply_ownership / _check_writable wie oben (damit nicht
      irgendeine spätere chown/writeability-Fehlermeldung den Fehler überdeckt).
    - Wir mocken Path.mkdir so, dass NUR downloads_dir fehlschlägt.
    """

    config_dir = tmp_path / "config"
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"

    def fake_apply_ownership(path: Path, puid: int, pgid: int) -> None:
        return None

    def fake_check_writable(path: Path, puid: int, pgid: int) -> bool:
        return True

    monkeypatch.setattr(pvc, "_apply_ownership", fake_apply_ownership)
    monkeypatch.setattr(pvc, "_check_writable", fake_check_writable)

    original_mkdir = Path.mkdir

    def fake_mkdir(self: Path, *args, **kwargs):
        if self == downloads_dir:
            raise PermissionError("read-only")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    with pytest.raises(pvc.PreflightError) as excinfo:
        pvc.ensure_directories(
            config_dir=config_dir,
            downloads_dir=downloads_dir,
            music_dir=music_dir,
            puid=1000,
            pgid=1000,
        )

    message = str(excinfo.value)
    assert "Unable to create downloads directory" in message
    assert "read-only" in message
    assert str(downloads_dir) in message


def test_ensure_directories_validates_writability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Erwartung:
    - Wenn das Verzeichnis zwar erstellt werden kann, aber der Container-User (puid/pgid)
      laut _check_writable NICHT schreiben darf, dann soll ensure_directories()
      einen PreflightError werfen.
    - Die Meldung muss den chown-Hinweis mit der richtigen uid/gid enthalten.

    Um CI-deterministisch zu bleiben:
    - _apply_ownership wird gemockt -> kein echtes chown.
    - _check_writable wird gemockt -> False zurückgeben, um den Fehlerweg zu erzwingen.
    - Wir asserten auf die Fehlermeldung.
    """

    config_dir = tmp_path / "config"
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"

    def fake_apply_ownership(path: Path, puid: int, pgid: int) -> None:
        # pretend we tried to chown successfully
        return None

    def fake_check_writable(path: Path, puid: int, pgid: int) -> bool:
        # force "not writable" branch
        return False

    monkeypatch.setattr(pvc, "_apply_ownership", fake_apply_ownership)
    monkeypatch.setattr(pvc, "_check_writable", fake_check_writable)

    with pytest.raises(pvc.PreflightError) as excinfo:
        pvc.ensure_directories(
            config_dir=config_dir,
            downloads_dir=downloads_dir,
            music_dir=music_dir,
            puid=1000,
            pgid=1000,
        )

    message = str(excinfo.value)
    assert "Directory permissions reject container user writes." in message
    assert "sudo chown 1000:1000" in message
    assert str(config_dir) in message
