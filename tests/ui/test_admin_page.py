from fastapi.testclient import TestClient

from app.ui.session import fingerprint_api_key
from tests.ui.test_ui_auth import _assert_html_response, _create_client


def _cookies_header(client: TestClient) -> str:
    return "; ".join(f"{name}={value}" for name, value in client.cookies.items())


def _login(client: TestClient, api_key: str = "primary-key") -> None:
    response = client.post("/ui/login", data={"api_key": api_key}, follow_redirects=False)
    assert response.status_code == 303


def test_admin_page_forbidden_for_non_admin(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/admin", headers=headers)
        assert response.status_code == 403


def test_admin_page_renders_for_admin(monkeypatch) -> None:
    with _create_client(monkeypatch, extra_env={"UI_ROLE_DEFAULT": "admin"}) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/admin", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert "/ui/system" in html
        assert "/ui/settings" in html
        assert 'data-role="admin"' in html
        assert 'data-test="admin-system-link"' in html
        assert 'data-test="admin-settings-link"' in html


def test_admin_page_respects_role_overrides(monkeypatch) -> None:
    fingerprint = fingerprint_api_key("primary-key")
    env = {"UI_ROLE_OVERRIDES": f"{fingerprint}:admin"}
    with _create_client(monkeypatch, extra_env=env) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/admin", headers=headers)
        _assert_html_response(response)
        assert 'data-role="admin"' in response.text
