from __future__ import annotations

import os
import re

from fastapi.testclient import TestClient

from app.config import override_runtime_env
from app.dependencies import get_app_config
from app.main import app
from app.ui.session import fingerprint_api_key


def _create_client(monkeypatch, extra_env: dict[str, str] | None = None) -> TestClient:
    monkeypatch.setenv("HARMONY_API_KEYS", "primary-key")
    monkeypatch.setenv("UI_ROLE_DEFAULT", "operator")
    monkeypatch.setenv("UI_ROLE_OVERRIDES", "")
    monkeypatch.setenv("UI_FEATURE_SPOTIFY", "true")
    monkeypatch.setenv("UI_FEATURE_SOULSEEK", "true")
    monkeypatch.setenv("UI_FEATURE_DLQ", "true")
    monkeypatch.setenv("UI_FEATURE_IMPORTS", "true")
    if extra_env:
        for key, value in extra_env.items():
            monkeypatch.setenv(key, value)
    assert os.environ.get("HARMONY_API_KEYS") == "primary-key"
    override_runtime_env(None)
    get_app_config.cache_clear()
    config = get_app_config()
    assert config.security.api_keys
    return TestClient(app)


def test_login_success(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        assert client.app.state.config_snapshot.security.api_keys
        response = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/ui"
        session_cookie = response.cookies.get("ui_session")
        csrf_cookie = response.cookies.get("csrftoken")
        assert session_cookie
        assert csrf_cookie

        cookie_header = f"ui_session={session_cookie}; csrftoken={csrf_cookie}"
        dashboard = client.get("/ui/", headers={"Cookie": cookie_header})
        assert dashboard.status_code == 200
        body = dashboard.text
        assert 'data-role="operator"' in body
        dashboard_token = dashboard.cookies.get("csrftoken")
        assert dashboard_token
        dashboard_token = dashboard_token.replace('"', "")
        meta_match = re.search(r'<meta name="csrf-token" content="([^"]*)"', body)
        assert meta_match is not None
        assert dashboard_token in meta_match.group(1)


def test_login_failure(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        response = client.post("/ui/login", data={"api_key": "wrong"}, follow_redirects=False)
        assert response.status_code == 400
        assert "Login failed" in response.text
        assert response.cookies.get("ui_session") is None


def test_role_gating(monkeypatch) -> None:
    fingerprint = fingerprint_api_key("primary-key")
    extra = {"UI_ROLE_OVERRIDES": f"{fingerprint}:read_only"}
    with _create_client(monkeypatch, extra_env=extra) as client:
        login = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
        assert login.status_code == 303
        cookie_header = "; ".join(f"{name}={value}" for name, value in login.cookies.items())
        page = client.get("/ui/", headers={"Cookie": cookie_header})
        assert page.status_code == 200
        html = page.text
        assert "operator-action" not in html
        assert "admin-action" not in html
        assert 'data-role="read_only"' in html


def test_csrf_enforcement(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        login = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
        assert login.status_code == 303
        cookie_header = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
        forbidden = client.post(
            "/ui/logout",
            follow_redirects=False,
            headers={"Cookie": cookie_header},
        )
        assert forbidden.status_code == 403

        token = client.cookies.get("csrftoken")
        assert token
        token = token.replace('"', "")
        cookie_header = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
        allowed = client.post(
            "/ui/logout",
            follow_redirects=False,
            headers={"X-CSRF-Token": token, "Cookie": cookie_header},
        )
        assert allowed.status_code == 303
        assert allowed.headers["location"] == "/ui/login"
