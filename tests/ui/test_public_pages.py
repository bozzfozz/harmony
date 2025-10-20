from __future__ import annotations

from fastapi.testclient import TestClient
from starlette import status

from tests.ui.test_ui_auth import _assert_html_response, _create_client


def _login(client: TestClient) -> str:
    response = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    return "; ".join(f"{name}={value}" for name, value in response.cookies.items())


def _assert_no_store(response) -> None:
    header = response.headers.get("cache-control")
    assert header is not None
    directives = [part.strip().lower() for part in header.split(",") if part.strip()]
    assert "no-store" in directives
    for directive in directives:
        if not directive.startswith("max-age="):
            continue
        _, _, raw_value = directive.partition("=")
        raw_value = raw_value.strip()
        try:
            value = int(raw_value)
        except ValueError:
            continue
        assert value <= 0


def test_dashboard_page_sets_no_store(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        cookie_header = _login(client)
        response = client.get("/ui/", headers={"Cookie": cookie_header})
        _assert_html_response(response)
        _assert_no_store(response)


def test_spotify_page_sets_no_store(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        cookie_header = _login(client)
        response = client.get("/ui/spotify", headers={"Cookie": cookie_header})
        _assert_html_response(response)
        _assert_no_store(response)
