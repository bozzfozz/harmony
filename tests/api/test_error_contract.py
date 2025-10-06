from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import HTTPException, status

from app.main import app
from tests.simple_client import SimpleTestClient


@pytest.fixture
def client() -> SimpleTestClient:
    with SimpleTestClient(app) as instance:
        yield instance


@pytest.fixture
def add_temp_route() -> Callable[[str, Callable[..., Any]], None]:
    registered_paths: list[str] = []

    def register(path: str, handler: Callable[..., Any]) -> None:
        app.add_api_route(path, handler, include_in_schema=False)
        registered_paths.append(path)

    yield register

    app.router.routes = [
        route for route in app.router.routes if getattr(route, "path", None) not in registered_paths
    ]
    if registered_paths:
        app.openapi_schema = None


def test_request_validation_error_envelope(client: SimpleTestClient) -> None:
    response = client.post(
        "/spotify/import/free",
        json={"playlist_links": "not-a-list"},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["message"] == "Request validation failed."
    fields = payload["error"].get("meta", {}).get("fields", [])
    assert any(field["name"] == "playlist_links" for field in fields)


def test_not_found_uses_standard_error_envelope(client: SimpleTestClient) -> None:
    response = client.get("/no-such-endpoint", use_raw_path=True)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {
        "ok": False,
        "error": {"code": "NOT_FOUND", "message": "Not Found"},
    }


def test_rate_limit_includes_retry_after_header(
    client: SimpleTestClient, add_temp_route: Callable[[str, Callable[..., Any]], None]
) -> None:
    async def rate_limited() -> None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": "2"},
        )

    add_temp_route("/__test__/rate-limited", rate_limited)

    response = client.get("/__test__/rate-limited", use_raw_path=True)

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    body = response.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["message"] == "Too many requests"
    assert body["error"]["meta"]["retry_after_ms"] >= 2000
    retry_after = response.headers.get("Retry-After") or response.headers.get("retry-after")
    assert retry_after == "2"


def test_unhandled_exception_translates_to_internal_error(
    client: SimpleTestClient, add_temp_route: Callable[[str, Callable[..., Any]], None]
) -> None:
    async def boom() -> None:
        raise RuntimeError("boom")

    add_temp_route("/__test__/boom", boom)

    response = client.get("/__test__/boom", use_raw_path=True)

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json() == {
        "ok": False,
        "error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
    }


def test_debug_header_present_when_envelope_disabled(
    client: SimpleTestClient,
    add_temp_route: Callable[[str, Callable[..., Any]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.errors._FEATURE_ENABLED", False)

    async def failing_handler() -> None:
        raise RuntimeError("boom")

    add_temp_route("/__test__/legacy-error", failing_handler)

    response = client.get("/__test__/legacy-error", use_raw_path=True)

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    debug_header = response.headers.get("X-Debug-Id") or response.headers.get("x-debug-id")
    assert debug_header is not None
    assert response.json() == {"detail": "An unexpected error occurred."}
