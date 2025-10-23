from __future__ import annotations

from collections.abc import Sequence
import os
import re
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest

from app.config import override_runtime_env
from app.dependencies import get_app_config
from app.main import app
from app.ui.services import (
    SpotifyFreeIngestAccepted,
    SpotifyFreeIngestResult,
    SpotifyFreeIngestSkipped,
    get_spotify_ui_service,
)
from app.ui.session import (
    fingerprint_api_key,
    register_ui_session_metrics,
    _resolve_login_rate_limit_config,
)
from app.utils import metrics

_CSRF_META_PATTERN = re.compile(r'<meta name="csrf-token" content="([^"]*)"')


def _assert_html_response(response, status_code: int = 200) -> None:
    assert response.status_code == status_code
    content_type = response.headers.get("content-type", "")
    assert "text/html" in content_type


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


def _cookie_header(response, name: str) -> str:
    header_values: list[str] = []
    headers = response.headers
    if hasattr(headers, "get_list"):
        header_values.extend(headers.get_list("set-cookie"))
    elif hasattr(headers, "getlist"):
        header_values.extend(headers.getlist("set-cookie"))
    else:
        value = headers.get("set-cookie")
        if value is not None:
            header_values.append(value)
    if not header_values and hasattr(headers, "raw"):
        header_values.extend(
            value.decode("latin-1")
            for key, value in headers.raw
            if key.decode("latin-1").lower() == "set-cookie"
        )
    for header in header_values:
        if header.startswith(f"{name}="):
            return header
    raise AssertionError(f"Cookie {name!r} not set")


def _metric_value(name: str, labels: dict[str, str]) -> float:
    registry = metrics.get_registry()
    for family in registry.collect():
        for sample in family.samples:
            if sample.name == name and sample.labels == labels:
                return float(sample.value)
    return 0.0


def test_login_page_renders_html(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        response = client.get("/ui/login")
        _assert_html_response(response)
        assert "Harmony Operator Console" in response.text


def test_dashboard_requires_session(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        response = client.get("/ui/")
        assert response.status_code == 401
        assert response.headers.get("content-type", "").startswith("application/json")


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
        _assert_html_response(dashboard)
        body = dashboard.text
        assert 'data-role="operator"' in body
    dashboard_token = dashboard.cookies.get("csrftoken")
    assert dashboard_token
    dashboard_token = dashboard_token.replace('"', "")
    meta_token = _CSRF_META_PATTERN.search(body)
    assert meta_token is not None
    assert dashboard_token in meta_token.group(1)
    assert 'name="csrftoken"' in body


def test_login_sets_insecure_cookies_by_default(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        response = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
        assert response.status_code == 303
        session_cookie = _cookie_header(response, "ui_session")
        csrf_cookie = _cookie_header(response, "csrftoken")
        assert "secure" not in session_cookie.lower()
        assert "secure" not in csrf_cookie.lower()


def test_login_allows_secure_cookies(monkeypatch) -> None:
    with _create_client(monkeypatch, extra_env={"UI_COOKIES_SECURE": "true"}) as client:
        response = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
        assert response.status_code == 303
        session_cookie = _cookie_header(response, "ui_session")
        csrf_cookie = _cookie_header(response, "csrftoken")
        assert "secure" in session_cookie.lower()
        assert "secure" in csrf_cookie.lower()


def test_login_failure(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        response = client.post("/ui/login", data={"api_key": "wrong"}, follow_redirects=False)
        assert response.status_code == 400
        assert "Login failed" in response.text
        assert response.cookies.get("ui_session") is None
        _assert_html_response(response, status_code=400)


def test_role_gating(monkeypatch) -> None:
    fingerprint = fingerprint_api_key("primary-key")
    extra = {"UI_ROLE_OVERRIDES": f"{fingerprint}:read_only"}
    with _create_client(monkeypatch, extra_env=extra) as client:
        login = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
        assert login.status_code == 303
        cookie_header = "; ".join(f"{name}={value}" for name, value in login.cookies.items())
        page = client.get("/ui/", headers={"Cookie": cookie_header})
        _assert_html_response(page)
        html = page.text
        assert "operator-action" not in html
        assert "admin-action" not in html
        assert 'data-role="read_only"' in html


def test_search_page_forbidden_for_read_only(monkeypatch) -> None:
    fingerprint = fingerprint_api_key("primary-key")
    extra = {"UI_ROLE_OVERRIDES": f"{fingerprint}:read_only"}
    with _create_client(monkeypatch, extra_env=extra) as client:
        login = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
        assert login.status_code == 303
        cookie_header = "; ".join(f"{name}={value}" for name, value in login.cookies.items())
        response = client.get("/ui/search", headers={"Cookie": cookie_header})
        assert response.status_code == 403
        assert response.headers.get("content-type", "").startswith("application/json")


@pytest.mark.parametrize(
    "path",
    (
        "/ui/soulseek",
        "/ui/soulseek/status",
        "/ui/soulseek/config",
        "/ui/soulseek/uploads",
        "/ui/soulseek/downloads",
    ),
)
def test_soulseek_routes_forbidden_for_read_only(monkeypatch, path: str) -> None:
    fingerprint = fingerprint_api_key("primary-key")
    extra = {"UI_ROLE_OVERRIDES": f"{fingerprint}:read_only"}
    with _create_client(monkeypatch, extra_env=extra) as client:
        login = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
        assert login.status_code == 303
        cookie_header = "; ".join(f"{name}={value}" for name, value in login.cookies.items())
        response = client.get(path, headers={"Cookie": cookie_header})
        assert response.status_code == 403
        assert response.headers.get("content-type", "").startswith("application/json")


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


def test_logout_form_token(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        login = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
        assert login.status_code == 303
        cookie_header = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
        dashboard = client.get("/ui/", headers={"Cookie": cookie_header})
        _assert_html_response(dashboard)
        token_cookie = client.cookies.get("csrftoken")
        assert token_cookie
        html = dashboard.text
        meta_token = _CSRF_META_PATTERN.search(html)
        assert meta_token is not None
        token = meta_token.group(1)
        cookie_header = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
        submission = client.post(
            "/ui/logout",
            data={"csrftoken": token},
            headers={"Cookie": cookie_header},
            follow_redirects=False,
        )
        assert submission.status_code == 303
        assert submission.headers["location"] == "/ui/login"


def test_session_metrics_increment_on_login_logout(monkeypatch) -> None:
    metrics.reset_registry()
    register_ui_session_metrics()

    with _create_client(monkeypatch) as client:
        assert (
            _metric_value(
                "ui_sessions_created_total",
                {"role": "operator"},
            )
            == 0.0
        )
        assert (
            _metric_value(
                "ui_sessions_terminated_total",
                {"role": "operator", "reason": "logout"},
            )
            == 0.0
        )

        login = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
        assert login.status_code == 303

        assert (
            _metric_value(
                "ui_sessions_created_total",
                {"role": "operator"},
            )
            == 1.0
        )

        token = client.cookies.get("csrftoken")
        assert token
        token = token.replace('"', "")
        cookie_header = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
        logout = client.post(
            "/ui/logout",
            follow_redirects=False,
            headers={"X-CSRF-Token": token, "Cookie": cookie_header},
        )
        assert logout.status_code == 303

        assert (
            _metric_value(
                "ui_sessions_terminated_total",
                {"role": "operator", "reason": "logout"},
            )
            == 1.0
        )


class _JobTrackingSpotifyService:
    def __init__(self) -> None:
        self.free_import_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        self.free_ingest_status_calls: list[str | None] = []
        self.free_import_result = SpotifyFreeIngestResult(
            ok=True,
            job_id="job-alpha",
            accepted=SpotifyFreeIngestAccepted(playlists=1, tracks=1, batches=1),
            skipped=SpotifyFreeIngestSkipped(playlists=0, tracks=0, reason=None),
            error=None,
        )
        self._stored_result: SpotifyFreeIngestResult | None = None
        self._stored_error: str | None = None

    async def free_import(
        self,
        *,
        playlist_links: Sequence[str] | None = None,
        tracks: Sequence[str] | None = None,
        batch_hint: int | None = None,
    ) -> SpotifyFreeIngestResult:
        self.free_import_calls.append((tuple(playlist_links or ()), tuple(tracks or ())))
        self._stored_result = self.free_import_result
        self._stored_error = None
        return self.free_import_result

    def consume_free_ingest_feedback(self) -> tuple[SpotifyFreeIngestResult | None, str | None]:
        result = self._stored_result
        error = self._stored_error
        self._stored_result = None
        self._stored_error = None
        return result, error

    async def free_ingest_job_status(self, job_id: str | None) -> None:
        self.free_ingest_status_calls.append(job_id)
        return None


def test_sessions_keep_independent_free_ingest_jobs(monkeypatch) -> None:
    stub = _JobTrackingSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            login_one = client.post(
                "/ui/login",
                data={"api_key": "primary-key"},
                follow_redirects=False,
            )
            assert login_one.status_code == 303
            cookie_header_one = "; ".join(
                f"{name}={value}" for name, value in login_one.cookies.items()
            )
            dashboard_one = client.get("/ui/", headers={"Cookie": cookie_header_one})
            _assert_html_response(dashboard_one)
            token_match = _CSRF_META_PATTERN.search(dashboard_one.text)
            assert token_match is not None
            cookie_header_one = "; ".join(
                f"{name}={value}" for name, value in client.cookies.items()
            )
            headers_one = {
                "Cookie": cookie_header_one,
                "X-CSRF-Token": token_match.group(1),
            }
            ingest_response = client.post(
                "/ui/spotify/free/run",
                data={"playlist_links": "https://open.spotify.com/playlist/demo"},
                headers=headers_one,
            )
            _assert_html_response(ingest_response)
            assert stub.free_ingest_status_calls[-1] == stub.free_import_result.job_id

            login_two = client.post(
                "/ui/login",
                data={"api_key": "primary-key"},
                follow_redirects=False,
            )
            assert login_two.status_code == 303
            cookies_two = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
            fragment_two = client.get(
                "/ui/spotify/free",
                headers={"Cookie": cookies_two},
            )
            _assert_html_response(fragment_two)
            assert stub.free_ingest_status_calls[-1] is None
            assert stub.free_import_result.job_id not in fragment_two.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_session_survives_manager_recreation(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        login = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
        assert login.status_code == 303
        manager_one = getattr(client.app.state, "ui_session_manager", None)
        assert manager_one is not None

        cookie_header = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
        client.app.state.ui_session_manager = None

        dashboard = client.get("/ui/", headers={"Cookie": cookie_header})
        _assert_html_response(dashboard)
        manager_two = getattr(client.app.state, "ui_session_manager", None)
        assert manager_two is not None
        assert manager_two is not manager_one


def test_session_persists_across_clients(monkeypatch) -> None:
    with _create_client(monkeypatch) as first_client:
        login = first_client.post(
            "/ui/login",
            data={"api_key": "primary-key"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        cookie_header = "; ".join(f"{name}={value}" for name, value in first_client.cookies.items())

    with _create_client(monkeypatch) as second_client:
        response = second_client.get("/ui/", headers={"Cookie": cookie_header})
        _assert_html_response(response)


def test_login_rate_limit_uses_configured_budget(monkeypatch) -> None:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    current = [base]

    def fake_now() -> datetime:
        return current[0]

    monkeypatch.setattr("app.ui.session._utcnow", fake_now)

    with _create_client(monkeypatch) as client:
        config = _resolve_login_rate_limit_config()
        assert config is not None
        attempts = config.attempts
        window_seconds = int(config.window.total_seconds())

        for _ in range(attempts):
            current[0] = base
            response = client.post(
                "/ui/login",
                data={"api_key": "wrong"},
                follow_redirects=False,
            )
            assert response.status_code == 400

        limited = client.post(
            "/ui/login",
            data={"api_key": "wrong"},
            follow_redirects=False,
        )
        assert limited.status_code == 429
        assert limited.headers.get("retry-after") == str(window_seconds)


def test_login_rate_limit_repeated_invalid(monkeypatch) -> None:
    current = [datetime(2024, 1, 1, tzinfo=UTC)]

    def fake_now() -> datetime:
        return current[0]

    monkeypatch.setattr("app.ui.session._utcnow", fake_now)
    env = {
        "UI_LOGIN_RATE_LIMIT_ATTEMPTS": "2",
        "UI_LOGIN_RATE_LIMIT_WINDOW_SECONDS": "60",
    }
    with _create_client(monkeypatch, extra_env=env) as client:
        first = client.post("/ui/login", data={"api_key": "wrong"}, follow_redirects=False)
        assert first.status_code == 400

        second = client.post("/ui/login", data={"api_key": "wrong"}, follow_redirects=False)
        assert second.status_code == 400

        third = client.post("/ui/login", data={"api_key": "wrong"}, follow_redirects=False)
        assert third.status_code == 429
        assert third.headers.get("retry-after") == "60"


def test_login_rate_limit_recovers_after_timeout(monkeypatch) -> None:
    current = [datetime(2024, 1, 1, tzinfo=UTC)]

    def fake_now() -> datetime:
        return current[0]

    monkeypatch.setattr("app.ui.session._utcnow", fake_now)
    env = {
        "UI_LOGIN_RATE_LIMIT_ATTEMPTS": "2",
        "UI_LOGIN_RATE_LIMIT_WINDOW_SECONDS": "60",
    }
    with _create_client(monkeypatch, extra_env=env) as client:
        client.post("/ui/login", data={"api_key": "wrong"}, follow_redirects=False)
        client.post("/ui/login", data={"api_key": "wrong"}, follow_redirects=False)
        limited = client.post("/ui/login", data={"api_key": "wrong"}, follow_redirects=False)
        assert limited.status_code == 429

        current[0] = current[0] + timedelta(seconds=61)

        retry = client.post("/ui/login", data={"api_key": "wrong"}, follow_redirects=False)
        assert retry.status_code == 400

        success = client.post(
            "/ui/login",
            data={"api_key": "primary-key"},
            follow_redirects=False,
        )
        assert success.status_code == 303
