from sqlalchemy import select

from app.db import session_scope
from app.models import Setting


def _insert_settings(values: dict[str, str | None]) -> None:
    with session_scope() as session:
        for key, value in values.items():
            existing = session.execute(
                select(Setting).where(Setting.key == key)
            ).scalar_one_or_none()
            if existing is not None:
                existing.value = value
                continue
            session.add(Setting(key=key, value=value))


def test_status_connections_reports_health(client) -> None:
    _insert_settings(
        {
            "SPOTIFY_CLIENT_ID": "client",
            "SPOTIFY_CLIENT_SECRET": None,
            "SPOTIFY_REDIRECT_URI": "http://localhost/callback",
            # Intentionally omit secret to trigger fail state
            "PLEX_BASE_URL": "http://plex",
            "PLEX_TOKEN": "token",
            "SLSKD_URL": "http://slskd",
        }
    )

    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert "connections" in payload
    assert payload["connections"]["spotify"] == "fail"
    assert payload["connections"]["plex"] == "ok"
    assert payload["connections"]["soulseek"] == "ok"
