from __future__ import annotations

import asyncio
from typing import Dict

from fastapi import status

from app.db import session_scope
from app.models import Setting
from app.workers.scan_worker import ScanWorker
from tests.simple_client import SimpleTestClient


def test_plex_status(client: SimpleTestClient) -> None:
    response = client.get("/plex/status")
    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["status"] == "connected"
    assert payload["library"] == {"artists": 2, "albums": 3, "tracks": 5}


def test_library_endpoints(client: SimpleTestClient) -> None:
    response = client.get("/plex/library/sections")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["MediaContainer"]["Directory"][0]["title"] == "Music"

    response = client.get("/plex/library/sections/1/all", params={"type": "8"})
    assert response.status_code == status.HTTP_200_OK
    assert "MediaContainer" in response.json()

    response = client.get("/plex/library/metadata/100")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["title"] == "Test Item"


def test_session_endpoints(client: SimpleTestClient) -> None:
    response = client.get("/plex/status/sessions")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["MediaContainer"]["size"] == 1

    response = client.get("/plex/status/sessions/history/all")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["MediaContainer"]["size"] == 1


def test_timeline_and_scrobble(client: SimpleTestClient) -> None:
    response = client.get("/plex/timeline", params={"ratingKey": "1"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["timeline"] == {"ratingKey": "1"}

    response = client.post("/plex/timeline", json={"time": 1000})
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == "ok"

    response = client.post("/plex/scrobble", json={"key": "100"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == "ok"

    response = client.post("/plex/unscrobble", json={"key": "100"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == "ok"


def test_playlists_and_playqueue(client: SimpleTestClient) -> None:
    response = client.get("/plex/playlists")
    assert response.status_code == status.HTTP_200_OK

    response = client.post("/plex/playlists", json={"title": "New"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "created"

    response = client.put("/plex/playlists/42", json={"title": "Updated"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "updated"

    response = client.delete("/plex/playlists/42")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "deleted"

    response = client.post("/plex/playQueues", json={"uri": "library://1"})
    assert response.status_code == status.HTTP_200_OK
    playqueue_id = response.json()["playQueueID"]

    response = client.get(f"/plex/playQueues/{playqueue_id}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["uri"] == "library://1"


def test_rating_and_tags(client: SimpleTestClient) -> None:
    response = client.post("/plex/rate", json={"key": "100", "rating": 5})
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == "ok"

    response = client.post("/plex/tags/100", json={"collection": ["Favorites"]})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["tags"] == {"collection": ["Favorites"]}


def test_devices_and_livetv(client: SimpleTestClient) -> None:
    response = client.get("/plex/devices")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["MediaContainer"]["Device"][0]["name"] == "Player"

    response = client.get("/plex/dvr")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["MediaContainer"]["Directory"][0]["name"] == "DVR"

    response = client.get("/plex/livetv")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["MediaContainer"]["Directory"][0]["name"] == "Channel"


def test_notifications(client: SimpleTestClient) -> None:
    response = client.get("/plex/notifications")
    assert response.status_code == status.HTTP_200_OK
    assert b"data: event" in response._body


def test_scan_worker_updates_status(client: SimpleTestClient) -> None:
    plex_stub = client.app.state.plex_stub
    worker = ScanWorker(plex_stub)

    asyncio.get_event_loop().run_until_complete(worker._perform_scan())

    with session_scope() as session:
        stored_settings: Dict[str, str] = {
            setting.key: setting.value
            for setting in session.query(Setting).all()
            if setting.key.startswith("plex_")
        }

    assert stored_settings["plex_artist_count"] == "2"
    assert stored_settings["plex_album_count"] == "3"
    assert stored_settings["plex_track_count"] == "5"
    assert "T" in stored_settings["plex_last_scan"]
