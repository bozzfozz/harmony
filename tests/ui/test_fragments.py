from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.services.watchlist_service import WatchlistService
from app.ui.session import fingerprint_api_key
from app.utils.activity import activity_manager

from tests.ui.test_ui_auth import _create_client


def _cookies_header(client: TestClient) -> str:
    return "; ".join(f"{name}={value}" for name, value in client.cookies.items())


def _login(client: TestClient, api_key: str = "primary-key") -> None:
    response = client.post("/ui/login", data={"api_key": api_key}, follow_redirects=False)
    assert response.status_code == 303


def _extract_csrf_token(html: str) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_activity_fragment_requires_session(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        response = client.get("/ui/activity/table")
        assert response.status_code == 401


def test_activity_fragment_renders_table(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        activity_manager.record(action_type="test", status="ok")
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/activity/table", headers=headers)
        assert response.status_code == 200
        body = response.text
        assert "<table" in body
        assert "data-total" in body


def test_watchlist_fragment_enforces_role(monkeypatch) -> None:
    fingerprint = fingerprint_api_key("primary-key")
    extra_env = {"UI_ROLE_OVERRIDES": f"{fingerprint}:read_only"}
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/watchlist/table", headers=headers)
        assert response.status_code == 403


def test_watchlist_create_requires_csrf(monkeypatch) -> None:
    WatchlistService().reset()
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.post(
            "/ui/watchlist",
            data={"artist_key": "spotify:artist:1"},
            headers=headers,
        )
        assert response.status_code == 403


def test_watchlist_create_success(monkeypatch) -> None:
    WatchlistService().reset()
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        dashboard = client.get("/ui/", headers=headers)
        assert dashboard.status_code == 200
        csrf_token = _extract_csrf_token(dashboard.text)
        token_cookie = client.cookies.get("csrftoken")
        assert token_cookie is not None
        submission = client.post(
            "/ui/watchlist",
            data={"artist_key": "spotify:artist:42", "priority": "2"},
            headers={
                "Cookie": _cookies_header(client),
                "X-CSRF-Token": csrf_token,
            },
        )
        assert submission.status_code == 200
        html = submission.text
        assert "spotify:artist:42" in html
        assert "<table" in html
        assert "data-count" in html
