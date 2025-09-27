from __future__ import annotations

import pytest

try:
    from app.core.plex_client import PlexClientAuthError, PlexClientNotFoundError
except ModuleNotFoundError:  # pragma: no cover - archived integration
    pytest.skip("Plex integration archived in MVP", allow_module_level=True)

from tests.simple_client import SimpleTestClient


class DummyScanWorker:
    def __init__(self, should_queue: bool = True) -> None:
        self.should_queue = should_queue
        self.requests: list[str | None] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def request_scan(self, section_id: str | None = None) -> bool:
        self.requests.append(section_id)
        return self.should_queue


def test_status_ok(client: SimpleTestClient) -> None:
    response = client.get("/plex/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "ok": True,
        "server": {"name": "Stub Plex", "version": "1.0"},
        "libraries": 1,
    }


def test_status_auth_error(monkeypatch: pytest.MonkeyPatch, client: SimpleTestClient) -> None:
    plex_stub = client.app.state.plex_stub

    async def raise_auth_error() -> None:
        raise PlexClientAuthError("bad token", status=401)

    monkeypatch.setattr(plex_stub, "get_status", raise_auth_error)
    response = client.get("/plex/status")
    assert response.status_code == 401
    payload = response.json()
    assert payload["error"]["code"] == "AUTH_ERROR"


def test_libraries_list(client: SimpleTestClient) -> None:
    response = client.get("/plex/libraries")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"] == [{"section_id": "1", "title": "Music", "type": "artist"}]


def test_scan_triggers_with_worker(
    monkeypatch: pytest.MonkeyPatch, client: SimpleTestClient
) -> None:
    worker = DummyScanWorker(should_queue=True)
    client.app.state.scan_worker = worker

    response = client.post("/plex/library/1/scan")
    assert response.status_code == 202
    payload = response.json()
    assert payload == {"ok": True, "queued": True, "section_id": "1"}
    assert worker.requests == ["1"]


def test_scan_direct_when_worker_missing(client: SimpleTestClient) -> None:
    client.app.state.scan_worker = None
    plex_stub = client.app.state.plex_stub
    plex_stub.refresh_calls.clear()

    response = client.post("/plex/library/1/scan")
    assert response.status_code == 202
    payload = response.json()
    assert payload == {"ok": True, "queued": True, "section_id": "1"}
    assert plex_stub.refresh_calls == [("1", False)]


def test_scan_not_found(monkeypatch: pytest.MonkeyPatch, client: SimpleTestClient) -> None:
    client.app.state.scan_worker = None
    plex_stub = client.app.state.plex_stub

    async def raise_not_found(section_id: str, *, full: bool = False) -> None:  # type: ignore[unused-ignore]
        raise PlexClientNotFoundError("missing", status=404)

    monkeypatch.setattr(plex_stub, "refresh_library_section", raise_not_found)
    response = client.post("/plex/library/999/scan")
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "NOT_FOUND"


def test_search_endpoint(client: SimpleTestClient) -> None:
    response = client.get("/plex/search", params={"q": "Track", "type": "track"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"], "Expected search results"
    first = payload["data"][0]
    assert {"type", "title", "guid", "ratingKey", "section_id"}.issubset(first.keys())


def test_search_invalid_type(client: SimpleTestClient) -> None:
    response = client.get("/plex/search", params={"q": "Track", "type": "invalid"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_tracks_endpoint(client: SimpleTestClient) -> None:
    response = client.get("/plex/tracks", params={"artist": "Plex Artist", "album": "Test Album"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"], "Expected track listing"
    first = payload["data"][0]
    assert first["title"] == "Test Track One"
    assert first["section_id"] == "1"


def test_tracks_missing_params(client: SimpleTestClient) -> None:
    response = client.get("/plex/tracks")
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
