from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from fastapi import FastAPI, Request
from tests.simple_client import SimpleTestClient

from app.api import spotify_free_links as free_links_module
from app.api.spotify_free_links import get_free_ingest_service
from app.dependencies import get_app_config
from app.errors import AppError


class StubFreeIngestService:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._result = SimpleNamespace(accepted_ids=[], duplicate_ids=[], error=None)

    def set_result(
        self,
        *,
        accepted_ids: list[str] | None = None,
        duplicate_ids: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        self._result = SimpleNamespace(
            accepted_ids=list(accepted_ids or []),
            duplicate_ids=list(duplicate_ids or []),
            error=error,
        )

    async def enqueue_playlists(self, playlist_ids: list[str]) -> SimpleNamespace:
        self.calls.append(list(playlist_ids))
        return SimpleNamespace(
            accepted_ids=list(self._result.accepted_ids),
            duplicate_ids=list(self._result.duplicate_ids),
            error=self._result.error,
        )


@pytest.fixture
def client() -> Callable[[StubFreeIngestService], SimpleTestClient]:
    instances: list[SimpleTestClient] = []

    def _factory(stub: StubFreeIngestService) -> SimpleTestClient:
        test_app = FastAPI()

        @test_app.exception_handler(AppError)
        async def _handle_app_error(request: Request, exc: AppError):
            return exc.as_response(request_path=request.url.path, method=request.method)

        test_app.include_router(free_links_module.router, prefix="/api/v1")
        test_app.dependency_overrides[get_free_ingest_service] = lambda: stub
        context = SimpleTestClient(test_app)
        client_instance = context.__enter__()
        instances.append(context)
        return client_instance

    yield _factory

    while instances:
        context = instances.pop()
        context.__exit__(None, None, None)


def test_accepts_single_and_multiple_urls(
    client: Callable[[StubFreeIngestService], SimpleTestClient],
) -> None:
    stub = StubFreeIngestService()
    stub.set_result(accepted_ids=["AAA"])
    test_client = client(stub)

    response = test_client.post(
        "/api/v1/spotify/free/links",
        json={"url": "https://open.spotify.com/playlist/AAA?si=123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == [
        {"playlist_id": "AAA", "url": "https://open.spotify.com/playlist/AAA"}
    ]
    assert body["skipped"] == []
    assert stub.calls[0] == ["AAA"]

    stub.set_result(accepted_ids=["BBB", "CCC"])
    response = test_client.post(
        "/api/v1/spotify/free/links",
        json={
            "urls": ["https://open.spotify.com/playlist/BBB", "spotify:playlist:CCC"]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert {(entry["playlist_id"], entry["url"]) for entry in body["accepted"]} == {
        ("BBB", "https://open.spotify.com/playlist/BBB"),
        ("CCC", "https://open.spotify.com/playlist/CCC"),
    }
    assert body["skipped"] == []


def test_rejects_non_playlist_urls_and_malformed_inputs(
    client: Callable[[StubFreeIngestService], SimpleTestClient],
) -> None:
    stub = StubFreeIngestService()
    test_client = client(stub)

    response = test_client.post(
        "/api/v1/spotify/free/links",
        json={
            "urls": [
                "https://example.com/not-spotify",
                "spotify:track:abc123",
                "",
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == []
    skipped = {(entry["url"], entry["reason"]) for entry in body["skipped"]}
    assert skipped == {
        ("https://example.com/not-spotify", "invalid"),
        ("spotify:track:abc123", "non_playlist"),
        ("", "invalid"),
    }
    assert stub.calls == []

    empty_response = test_client.post(
        "/api/v1/spotify/free/links",
        json={"urls": []},
    )
    assert empty_response.status_code == 400
    assert empty_response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_deduplicates_by_playlist_id(
    client: Callable[[StubFreeIngestService], SimpleTestClient],
) -> None:
    stub = StubFreeIngestService()
    stub.set_result(accepted_ids=["AAA"])
    test_client = client(stub)

    response = test_client.post(
        "/api/v1/spotify/free/links",
        json={
            "urls": [
                "https://open.spotify.com/playlist/AAA?si=123",
                "spotify:playlist:AAA",
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == [
        {"playlist_id": "AAA", "url": "https://open.spotify.com/playlist/AAA"}
    ]
    assert body["skipped"] == [{"url": "spotify:playlist:AAA", "reason": "duplicate"}]
    assert stub.calls[0] == ["AAA"]


def test_accepts_user_playlist_urls_when_enabled(
    client: Callable[[StubFreeIngestService], SimpleTestClient],
) -> None:
    from app import dependencies as deps

    deps.get_app_config.cache_clear()
    config = deepcopy(deps.get_app_config())
    config.spotify.free_accept_user_urls = True

    stub = StubFreeIngestService()
    stub.set_result(accepted_ids=["AAA"])
    test_client = client(stub)
    test_client.app.dependency_overrides[get_app_config] = lambda config=config: config

    response = test_client.post(
        "/api/v1/spotify/free/links",
        json={"urls": ["https://open.spotify.com/user/foo/playlist/AAA?si=xyz"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == [
        {"playlist_id": "AAA", "url": "https://open.spotify.com/playlist/AAA"}
    ]
    assert body["skipped"] == []
    assert stub.calls[-1] == ["AAA"]

    stub.set_result(accepted_ids=["BBB"])
    response = test_client.post(
        "/api/v1/spotify/free/links",
        json={"urls": ["spotify:user:bar:playlist:BBB"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == [
        {"playlist_id": "BBB", "url": "https://open.spotify.com/playlist/BBB"}
    ]
    assert body["skipped"] == []
    assert stub.calls[-1] == ["BBB"]

    test_client.app.dependency_overrides.pop(get_app_config, None)


def test_enqueues_via_free_ingest_service(
    client: Callable[[StubFreeIngestService], SimpleTestClient],
) -> None:
    stub = StubFreeIngestService()
    stub.set_result(accepted_ids=["AAA"], duplicate_ids=["BBB"])
    test_client = client(stub)

    response = test_client.post(
        "/api/v1/spotify/free/links",
        json={
            "urls": [
                "https://open.spotify.com/playlist/AAA",
                "https://open.spotify.com/playlist/BBB",
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == [
        {"playlist_id": "AAA", "url": "https://open.spotify.com/playlist/AAA"}
    ]
    assert body["skipped"] == [
        {"url": "https://open.spotify.com/playlist/BBB", "reason": "duplicate"}
    ]
    assert stub.calls[0] == ["AAA", "BBB"]


def test_logs_api_request_event(
    client: Callable[[StubFreeIngestService], SimpleTestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = StubFreeIngestService()
    stub.set_result(accepted_ids=["AAA"])
    captured: list[str] = []

    original_log_event = free_links_module.log_event

    def _capture(event_logger: Any, event_name: str, /, **fields: Any) -> None:
        captured.append(event_name)
        original_log_event(event_logger, event_name, **fields)

    monkeypatch.setattr(free_links_module, "log_event", _capture)
    test_client = client(stub)

    response = test_client.post(
        "/api/v1/spotify/free/links",
        json={"url": "https://open.spotify.com/playlist/AAA"},
    )

    assert response.status_code == 200
    assert "api.request" in captured
