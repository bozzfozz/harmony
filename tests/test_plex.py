from __future__ import annotations

import asyncio
from sqlalchemy import select

from app.db import session_scope
from app.models import Setting
from app.workers.scan_worker import ScanWorker
from tests.simple_client import SimpleTestClient


def test_plex_status(client: SimpleTestClient) -> None:
    response = client.get("/plex/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "connected"
    assert payload["artist_count"] is None
    assert payload["album_count"] is None
    assert payload["track_count"] is None
    assert payload["last_scan"] is None


def test_plex_artists(client: SimpleTestClient) -> None:
    response = client.get("/plex/artists")
    assert response.status_code == 200
    assert response.json()[0]["name"] == "Tester"


def test_plex_tracks(client: SimpleTestClient) -> None:
    response = client.get("/plex/album/10/tracks")
    assert response.status_code == 200
    assert response.json()[0]["title"] == "Test Song"


def test_scan_worker_updates_status(client: SimpleTestClient) -> None:
    plex_stub = client.app.state.plex_stub
    worker = ScanWorker(plex_stub)

    asyncio.get_event_loop().run_until_complete(worker._perform_scan())

    with session_scope() as session:
        stored_settings = {
            setting.key: setting.value
            for setting in session.execute(
                select(Setting).where(
                    Setting.key.in_(
                        [
                            "plex_artist_count",
                            "plex_album_count",
                            "plex_track_count",
                            "plex_last_scan",
                        ]
                    )
                )
            ).scalars()
        }

    assert stored_settings["plex_artist_count"] == "2"
    assert stored_settings["plex_album_count"] == "2"
    assert stored_settings["plex_track_count"] == "3"
    assert "T" in stored_settings["plex_last_scan"]

    response = client.get("/plex/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["artist_count"] == 2
    assert payload["album_count"] == 2
    assert payload["track_count"] == 3
    assert payload["last_scan"] is not None
