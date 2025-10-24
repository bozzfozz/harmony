from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import FastAPI, status as fastapi_status
from fastapi.testclient import TestClient
import pytest

from app.api.watchlist import router as watchlist_router
from app.db import init_db
from app.dependencies import get_watchlist_service
from app.middleware.errors import setup_exception_handlers
from app.services.watchlist_service import WatchlistService


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture()
def watchlist_client() -> Iterator[TestClient]:
    get_watchlist_service.cache_clear()
    if not hasattr(fastapi_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
        setattr(
            fastapi_status,
            "HTTP_422_UNPROCESSABLE_CONTENT",
            fastapi_status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    init_db()
    app = FastAPI()
    setup_exception_handlers(app)
    app.state.api_base_path = "/api/v1"
    app.include_router(watchlist_router, prefix="/api/v1")
    service = WatchlistService()
    app.dependency_overrides[get_watchlist_service] = lambda: service

    with TestClient(app) as client:
        try:
            yield client
        finally:
            app.dependency_overrides.clear()
            get_watchlist_service.cache_clear()


def test_watchlist_crud_flow(watchlist_client: TestClient) -> None:
    list_response = watchlist_client.get("/api/v1/watchlist")
    assert list_response.status_code == 200
    assert list_response.json() == {"items": []}

    create_payload = {"artist_key": "spotify:artist-1", "priority": 5}
    create_response = watchlist_client.post("/api/v1/watchlist", json=create_payload)
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["artist_key"] == "spotify:artist-1"
    assert created["priority"] == 5
    assert created["paused"] is False
    assert created["pause_reason"] is None
    assert created["resume_at"] is None
    assert isinstance(created["id"], int)
    assert _parse_timestamp(created["created_at"]) is not None
    assert _parse_timestamp(created["updated_at"]) is not None

    list_after_create = watchlist_client.get("/api/v1/watchlist")
    assert list_after_create.status_code == 200
    items = list_after_create.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == created["id"]

    update_response = watchlist_client.patch(
        "/api/v1/watchlist/spotify:artist-1", json={"priority": 7}
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["priority"] == 7
    assert updated["paused"] is False
    assert updated["pause_reason"] is None

    resume_at = datetime(2025, 5, 4, 12, 0, tzinfo=UTC)
    pause_response = watchlist_client.post(
        "/api/v1/watchlist/spotify:artist-1/pause",
        json={"reason": "  Taking a break  ", "resume_at": resume_at.isoformat()},
    )
    assert pause_response.status_code == 200
    paused = pause_response.json()
    assert paused["paused"] is True
    assert paused["pause_reason"] == "Taking a break"
    assert _parse_timestamp(paused["resume_at"]) == resume_at

    resume_response = watchlist_client.post("/api/v1/watchlist/spotify:artist-1/resume")
    assert resume_response.status_code == 200
    resumed = resume_response.json()
    assert resumed["paused"] is False
    assert resumed["pause_reason"] is None
    assert resumed["resume_at"] is None

    delete_response = watchlist_client.delete("/api/v1/watchlist/spotify:artist-1")
    assert delete_response.status_code == 204
    assert delete_response.content == b""

    final_list = watchlist_client.get("/api/v1/watchlist")
    assert final_list.status_code == 200
    assert final_list.json() == {"items": []}


def test_create_watchlist_duplicate_artist_returns_conflict(
    watchlist_client: TestClient,
) -> None:
    payload = {"artist_key": "spotify:duplicate", "priority": 1}
    first_response = watchlist_client.post("/api/v1/watchlist", json=payload)
    assert first_response.status_code == 201

    duplicate_response = watchlist_client.post("/api/v1/watchlist", json=payload)
    assert duplicate_response.status_code == 409
    error = duplicate_response.json()
    assert error == {
        "ok": False,
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Artist already registered.",
            "meta": {"artist_key": "spotify:duplicate"},
        },
    }


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("PATCH", "/api/v1/watchlist/spotify:missing", {"priority": 3}),
        ("POST", "/api/v1/watchlist/spotify:missing/pause", {"reason": "Break"}),
        ("POST", "/api/v1/watchlist/spotify:missing/resume", None),
        ("DELETE", "/api/v1/watchlist/spotify:missing", None),
    ],
)
def test_watchlist_missing_entry_returns_not_found(
    watchlist_client: TestClient, method: str, path: str, payload: dict[str, object] | None
) -> None:
    request_kwargs: dict[str, object] = {}
    if payload is not None:
        request_kwargs["json"] = payload
    response = watchlist_client.request(method, path, **request_kwargs)
    assert response.status_code == 404
    error = response.json()
    assert error["ok"] is False
    assert error["error"]["code"] == "NOT_FOUND"
    assert error["error"]["message"] == "Watchlist entry not found."


def test_create_watchlist_validation_errors(watchlist_client: TestClient) -> None:
    response = watchlist_client.post("/api/v1/watchlist", json={"priority": 2})
    assert response.status_code == 422
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    fields = payload["error"].get("meta", {}).get("fields", [])
    assert any(field.get("name") == "artist_key" for field in fields)


def test_update_watchlist_priority_validation_error(watchlist_client: TestClient) -> None:
    create_response = watchlist_client.post(
        "/api/v1/watchlist", json={"artist_key": "spotify:test", "priority": 0}
    )
    assert create_response.status_code == 201

    response = watchlist_client.patch("/api/v1/watchlist/spotify:test", json={"priority": "high"})
    assert response.status_code == 422
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    fields = payload["error"].get("meta", {}).get("fields", [])
    assert any(field.get("name") == "priority" for field in fields)
