from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.config import load_config
from app.db import session_scope
from app.errors import ValidationAppError
from app.models import Setting


def _insert_settings(entries: dict[str, str | None]) -> None:
    with session_scope() as session:
        for key, value in entries.items():
            setting = session.execute(
                select(Setting).where(Setting.key == key)
            ).scalar_one_or_none()
            if setting is None:
                session.add(Setting(key=key, value=value))
            else:
                setting.value = value


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
def test_spotify_configuration_from_database(
    monkeypatch: pytest.MonkeyPatch, entries, expected
) -> None:
    for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI"):
        monkeypatch.delenv(key, raising=False)

    _insert_settings(entries)

    config = load_config()

    assert config.spotify.client_id == expected["client_id"]
    assert config.spotify.client_secret == expected["client_secret"]
    assert config.spotify.redirect_uri == expected["redirect_uri"]


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
    monkeypatch.setenv("SLSKD_URL", "http://env-slskd")

    with session_scope() as session:
        session.execute(delete(Setting).where(Setting.key.in_(["SPOTIFY_CLIENT_ID", "SLSKD_URL"])))
        session.commit()

    config = load_config()

    assert config.spotify.client_id == "env-client"
    assert config.soulseek.base_url == "http://env-slskd"


def test_configuration_supports_legacy_slskd_host_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SLSKD_URL", raising=False)
    monkeypatch.setenv("SLSKD_HOST", "slskd.local")
    monkeypatch.setenv("SLSKD_PORT", "2235")

    config = load_config()

    assert config.soulseek.base_url == "http://slskd.local:2235"


def test_load_config_rejects_non_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://user:pass@db/test")

    with pytest.raises(ValidationAppError):
        load_config()


def test_load_config_rejects_legacy_postgresql_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db/test")

    with pytest.raises(ValidationAppError):
        load_config()
