import pytest

from app.db import session_scope
from app.models import Setting


@pytest.fixture(autouse=True)
def clear_settings() -> None:
    with session_scope() as session:
        session.query(Setting).delete()


def _insert_settings(values: dict[str, str | None]) -> None:
    with session_scope() as session:
        for key, value in values.items():
            session.add(Setting(key=key, value=value))


def test_spotify_health_reports_missing_credentials(client) -> None:
    response = client.get("/api/health/spotify")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "spotify"
    assert payload["status"] == "fail"
    assert "SPOTIFY_CLIENT_ID" in payload["missing"]
    assert "SPOTIFY_CLIENT_SECRET" in payload["missing"]
    assert "SPOTIFY_REDIRECT_URI" in payload["missing"]


def test_spotify_health_ok_when_all_values_present(client) -> None:
    _insert_settings(
        {
            "SPOTIFY_CLIENT_ID": "client",
            "SPOTIFY_CLIENT_SECRET": "secret",
            "SPOTIFY_REDIRECT_URI": "http://localhost/callback",
        }
    )

    response = client.get("/api/health/spotify")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "spotify"
    assert payload["status"] == "ok"
    assert payload["missing"] == []


def test_plex_health_reports_optional_missing(client) -> None:
    _insert_settings({"PLEX_BASE_URL": "http://plex", "PLEX_TOKEN": "token"})

    response = client.get("/api/health/plex")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "plex"
    assert payload["status"] == "ok"
    assert payload["missing"] == []
    assert payload["optional_missing"] == ["PLEX_LIBRARY"]


def test_plex_health_requires_token(client) -> None:
    _insert_settings({"PLEX_BASE_URL": "http://plex"})

    response = client.get("/api/health/plex")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "fail"
    assert payload["missing"] == ["PLEX_TOKEN"]


def test_soulseek_health_accepts_missing_api_key(client) -> None:
    _insert_settings({"SLSKD_URL": "http://slskd"})

    response = client.get("/api/health/soulseek")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "soulseek"
    assert payload["status"] == "ok"
    assert payload["missing"] == []
    assert payload["optional_missing"] == ["SLSKD_API_KEY"]


def test_soulseek_health_requires_base_url(client) -> None:
    response = client.get("/api/health/soulseek")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "fail"
    assert payload["missing"] == ["SLSKD_URL"]
