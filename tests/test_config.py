from __future__ import annotations

import pytest

from app.config import load_config
from app.db import session_scope
from app.models import Setting


def _insert_settings(entries: dict[str, str | None]) -> None:
    with session_scope() as session:
        for key, value in entries.items():
            session.add(Setting(key=key, value=value))


@pytest.mark.parametrize(
    "entries,expected",
    [
        (
            {
                "SPOTIFY_CLIENT_ID": "db-client-id",
                "SPOTIFY_CLIENT_SECRET": "db-secret",
                "SPOTIFY_REDIRECT_URI": "http://localhost/callback",
            },
            {
                "client_id": "db-client-id",
                "client_secret": "db-secret",
                "redirect_uri": "http://localhost/callback",
            },
        ),
    ],
)
def test_spotify_configuration_from_database(monkeypatch: pytest.MonkeyPatch, entries, expected) -> None:
    for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI"):
        monkeypatch.delenv(key, raising=False)

    _insert_settings(entries)

    config = load_config()

    assert config.spotify.client_id == expected["client_id"]
    assert config.spotify.client_secret == expected["client_secret"]
    assert config.spotify.redirect_uri == expected["redirect_uri"]


def test_plex_configuration_from_database(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("PLEX_BASE_URL", "PLEX_URL", "PLEX_TOKEN", "PLEX_LIBRARY"):
        monkeypatch.delenv(key, raising=False)

    _insert_settings(
        {
            "PLEX_BASE_URL": "http://plex.local:32400",
            "PLEX_TOKEN": "db-token",
            "PLEX_LIBRARY": "Music",
        }
    )

    config = load_config()

    assert config.plex.base_url == "http://plex.local:32400"
    assert config.plex.token == "db-token"
    assert config.plex.library_name == "Music"


def test_soulseek_configuration_from_database(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SLSKD_URL", "SLSKD_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    _insert_settings(
        {
            "SLSKD_URL": "http://slskd:5030",
            "SLSKD_API_KEY": "db-api-key",
        }
    )

    config = load_config()

    assert config.soulseek.base_url == "http://slskd:5030"
    assert config.soulseek.api_key == "db-api-key"


def test_configuration_falls_back_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env-client")
    monkeypatch.setenv("PLEX_BASE_URL", "http://env-plex")
    monkeypatch.setenv("SLSKD_URL", "http://env-slskd")

    config = load_config()

    assert config.spotify.client_id == "env-client"
    assert config.plex.base_url == "http://env-plex"
    assert config.soulseek.base_url == "http://env-slskd"
