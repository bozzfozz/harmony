from fastapi.testclient import TestClient

from app.ui.session import fingerprint_api_key
from tests.ui.test_ui_auth import _assert_html_response, _create_client


def _cookies_header(client: TestClient) -> str:
    return "; ".join(f"{name}={value}" for name, value in client.cookies.items())


def _login(client: TestClient, api_key: str = "primary-key") -> None:
    response = client.post("/ui/login", data={"api_key": api_key}, follow_redirects=False)
    assert response.status_code == 303


def test_operations_page_renders_fragments(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/operations", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert "/ui/downloads/table" in html
        assert "/ui/jobs/table" in html
        assert "/ui/watchlist/table" in html
        assert "/ui/activity/table" in html


def test_operations_page_exposes_sse_mode(monkeypatch) -> None:
    with _create_client(monkeypatch, extra_env={"UI_LIVE_UPDATES": "SSE"}) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/operations", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert 'data-live-updates="sse"' in html
        assert 'data-live-event="downloads"' in html
        assert "/ui/events" in html


def test_operations_page_handles_disabled_dlq(monkeypatch) -> None:
    with _create_client(monkeypatch, extra_env={"UI_FEATURE_DLQ": "false"}) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/operations", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert "/ui/downloads/table" not in html
        assert "/ui/jobs/table" not in html
        assert "/ui/watchlist/table" in html
        assert "/ui/activity/table" in html


def test_downloads_page_requires_dlq_feature(monkeypatch) -> None:
    with _create_client(monkeypatch, extra_env={"UI_FEATURE_DLQ": "false"}) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/downloads", headers=headers)
        assert response.status_code == 404


def test_jobs_page_requires_dlq_feature(monkeypatch) -> None:
    with _create_client(monkeypatch, extra_env={"UI_FEATURE_DLQ": "false"}) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/jobs", headers=headers)
        assert response.status_code == 404


def test_watchlist_page_requires_operator_role(monkeypatch) -> None:
    fingerprint = fingerprint_api_key("primary-key")
    env = {"UI_ROLE_OVERRIDES": f"{fingerprint}:read_only"}
    with _create_client(monkeypatch, extra_env=env) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/watchlist", headers=headers)
        assert response.status_code == 403


def test_activity_page_available_for_read_only(monkeypatch) -> None:
    fingerprint = fingerprint_api_key("primary-key")
    env = {"UI_ROLE_OVERRIDES": f"{fingerprint}:read_only"}
    with _create_client(monkeypatch, extra_env=env) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/activity", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert "/ui/activity/table" in html


def test_watchlist_page_renders_form(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/watchlist", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert 'id="watchlist-create-form"' in html
        assert 'hx-post="/ui/watchlist"' in html
