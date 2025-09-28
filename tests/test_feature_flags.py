from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import delete

from app import dependencies as deps
from app.config import is_feature_enabled
from app.db import session_scope
from app.main import app
from app.models import Download, Setting
from app.utils.settings_store import write_setting
from tests.simple_client import SimpleTestClient


def _reset_config_cache() -> None:
    deps.get_app_config.cache_clear()


def test_flags_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_ARTWORK", raising=False)
    monkeypatch.delenv("ENABLE_LYRICS", raising=False)
    _reset_config_cache()

    with SimpleTestClient(app) as client:
        flags = client.app.state.feature_flags
        assert flags.enable_artwork is False
        assert flags.enable_lyrics is False
        assert flags.enable_legacy_routes is False

        artwork_response = client.get("/soulseek/download/999/artwork")
        assert artwork_response.status_code == 503
        assert artwork_response.json() == {
            "ok": False,
            "error": {
                "code": "DEPENDENCY_ERROR",
                "message": "Artwork feature is disabled by configuration.",
                "meta": {"feature": "artwork"},
            },
        }

        lyrics_response = client.get("/soulseek/download/999/lyrics")
        assert lyrics_response.status_code == 503
        assert lyrics_response.json() == {
            "ok": False,
            "error": {
                "code": "DEPENDENCY_ERROR",
                "message": "Lyrics feature is disabled by configuration.",
                "meta": {"feature": "lyrics"},
            },
        }

    _reset_config_cache()


def test_enable_legacy_routes_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_ENABLE_LEGACY_ROUTES", "1")
    _reset_config_cache()

    with SimpleTestClient(app) as client:
        flags = client.app.state.feature_flags
        assert flags.enable_legacy_routes is True

    monkeypatch.delenv("FEATURE_ENABLE_LEGACY_ROUTES", raising=False)
    _reset_config_cache()


def test_enable_artwork_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ENABLE_ARTWORK", "1")
    monkeypatch.setenv("ENABLE_LYRICS", "0")
    _reset_config_cache()

    audio_path = tmp_path / "track.mp3"
    audio_path.write_bytes(b"audio")
    artwork_path = tmp_path / "cover.jpg"
    artwork_path.write_bytes(b"cover")

    with session_scope() as session:
        download = Download(
            filename=str(audio_path),
            state="completed",
            progress=100.0,
            has_artwork=True,
            artwork_status="done",
            artwork_path=str(artwork_path),
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    with SimpleTestClient(app) as client:
        flags = client.app.state.feature_flags
        assert flags.enable_artwork is True
        assert flags.enable_lyrics is False

        artwork_response = client.get(f"/soulseek/download/{download_id}/artwork")
        assert artwork_response.status_code == 200
        assert artwork_response._body == b"cover"

        lyrics_response = client.get(f"/soulseek/download/{download_id}/lyrics")
        assert lyrics_response.status_code == 503

    _reset_config_cache()


def test_enable_lyrics_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ENABLE_ARTWORK", "0")
    monkeypatch.setenv("ENABLE_LYRICS", "1")
    _reset_config_cache()

    audio_path = tmp_path / "song.mp3"
    audio_path.write_bytes(b"audio")
    lyrics_path = tmp_path / "lyrics.lrc"
    lyrics_path.write_text("[00:00.00]Hello world", encoding="utf-8")

    with session_scope() as session:
        download = Download(
            filename=str(audio_path),
            state="completed",
            progress=100.0,
            has_lyrics=True,
            lyrics_status="done",
            lyrics_path=str(lyrics_path),
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    with SimpleTestClient(app) as client:
        flags = client.app.state.feature_flags
        assert flags.enable_artwork is False
        assert flags.enable_lyrics is True

        lyrics_response = client.get(f"/soulseek/download/{download_id}/lyrics")
        assert lyrics_response.status_code == 200
        assert lyrics_response._body.decode("utf-8") == "[00:00.00]Hello world"

        artwork_response = client.get(f"/soulseek/download/{download_id}/artwork")
        assert artwork_response.status_code == 503

    _reset_config_cache()


def test_is_feature_enabled_prefers_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_ARTWORK", "0")
    _reset_config_cache()

    write_setting("ENABLE_ARTWORK", "1")

    assert is_feature_enabled("artwork") is True

    with session_scope() as session:
        session.execute(delete(Setting).where(Setting.key == "ENABLE_ARTWORK"))
        session.commit()

    _reset_config_cache()
