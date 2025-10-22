import re

from fastapi import status
from fastapi.testclient import TestClient

from app.errors import AppError, ErrorCode
from app.ui.routes.system import get_system_ui_service
from app.ui.services.system import (
    IntegrationProviderStatus,
    IntegrationSummary,
    LivenessRecord,
    ReadinessDependency,
    ReadinessRecord,
    SecretValidationRecord,
    ServiceHealthBadge,
)
from app.ui.session import fingerprint_api_key
from tests.ui.test_ui_auth import _assert_html_response, _create_client


def _cookies_header(client: TestClient) -> str:
    return "; ".join(f"{name}={value}" for name, value in client.cookies.items())


def _login(client: TestClient, api_key: str = "primary-key") -> None:
    response = client.post("/ui/login", data={"api_key": api_key}, follow_redirects=False)
    assert response.status_code == 303


def _extract_csrf_token(html: str) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match is not None
    return match.group(1)


class _StubSystemService:
    def __init__(self) -> None:
        self.liveness = LivenessRecord(status="ok", ok=True, version="1.0", uptime_seconds=10.0)
        self.readiness = ReadinessRecord(
            ok=True,
            database="up",
            dependencies=(ReadinessDependency(name="redis", status="up"),),
            orchestrator_components=(),
            orchestrator_jobs=(),
            enabled_jobs={},
            error_message=None,
        )
        self.integrations = IntegrationSummary(
            overall="ok",
            providers=(IntegrationProviderStatus(name="spotify", status="ok", details=None),),
        )
        self.badges = (
            ServiceHealthBadge(service="spotify", status="ok", missing=(), optional_missing=()),
        )
        self.secret_result = SecretValidationRecord(
            provider="spotify_client_secret",
            mode="live",
            valid=True,
            validated_at=self._now(),
            reason=None,
            note="valid",
        )
        self.raise_error = False

    @staticmethod
    def _now():
        from datetime import UTC, datetime

        return datetime.now(tz=UTC)

    async def fetch_liveness(self, request):  # noqa: D401 - test stub signature
        if self.raise_error:
            raise AppError("failed", code=ErrorCode.DEPENDENCY_ERROR)
        return self.liveness

    async def fetch_readiness(self, request):
        return self.readiness

    async def fetch_integrations(self):
        return self.integrations

    async def fetch_service_badges(self):
        return self.badges

    async def validate_secret(self, request, *, provider: str, override: str | None, session):
        return self.secret_result


def test_system_page_renders_for_operator(monkeypatch) -> None:
    stub = _StubSystemService()
    with _create_client(monkeypatch) as client:
        client.app.dependency_overrides[get_system_ui_service] = lambda: stub
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/system", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert 'id="hx-system-liveness"' in html
        assert 'id="system-liveness-refresh"' in html
        assert 'hx-get="/ui/system/integrations"' in html
        assert 'hx-post="/ui/system/secrets/spotify_client_secret"' in html
    client.app.dependency_overrides.pop(get_system_ui_service, None)


def test_system_page_forbidden_for_read_only(monkeypatch) -> None:
    fingerprint = fingerprint_api_key("primary-key")
    env = {"UI_ROLE_OVERRIDES": f"{fingerprint}:read_only"}
    with _create_client(monkeypatch, extra_env=env) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/system", headers=headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN


def test_system_liveness_fragment_returns_markup(monkeypatch) -> None:
    stub = _StubSystemService()
    with _create_client(monkeypatch) as client:
        client.app.dependency_overrides[get_system_ui_service] = lambda: stub
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        fragment = client.get("/ui/system/liveness", headers=headers)
        _assert_html_response(fragment)
        assert "system-card__status-text" in fragment.text
    client.app.dependency_overrides.pop(get_system_ui_service, None)


def test_system_liveness_fragment_handles_error(monkeypatch) -> None:
    stub = _StubSystemService()
    stub.raise_error = True
    with _create_client(monkeypatch) as client:
        client.app.dependency_overrides[get_system_ui_service] = lambda: stub
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        fragment = client.get("/ui/system/liveness", headers=headers)
        assert fragment.status_code == status.HTTP_200_OK
        assert "Retry" in fragment.text
    client.app.dependency_overrides.pop(get_system_ui_service, None)


def test_secret_validation_requires_admin(monkeypatch) -> None:
    stub = _StubSystemService()
    with _create_client(monkeypatch) as client:
        client.app.dependency_overrides[get_system_ui_service] = lambda: stub
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.post("/ui/system/secrets/spotify_client_secret", headers=headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN
    client.app.dependency_overrides.pop(get_system_ui_service, None)


def test_secret_validation_updates_card(monkeypatch) -> None:
    stub = _StubSystemService()
    with _create_client(monkeypatch, extra_env={"UI_ROLE_DEFAULT": "admin"}) as client:
        client.app.dependency_overrides[get_system_ui_service] = lambda: stub
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        page = client.get("/ui/system", headers=headers)
        _assert_html_response(page)
        token = _extract_csrf_token(page.text)
        post_headers = {
            "Cookie": _cookies_header(client),
            "X-CSRF-Token": token,
        }
        response = client.post(
            "/ui/system/secrets/spotify_client_secret",
            headers=post_headers,
            data={"value": "override"},
        )
        _assert_html_response(response)
        assert "system-secret-card__status" in response.text
        assert "Live value" in response.text
    client.app.dependency_overrides.pop(get_system_ui_service, None)


def test_secret_validation_allows_admin_when_imports_disabled(monkeypatch) -> None:
    stub = _StubSystemService()
    extra_env = {"UI_ROLE_DEFAULT": "admin", "UI_FEATURE_IMPORTS": "false"}
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        client.app.dependency_overrides[get_system_ui_service] = lambda: stub
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        page = client.get("/ui/system", headers=headers)
        _assert_html_response(page)
        token = _extract_csrf_token(page.text)
        post_headers = {
            "Cookie": _cookies_header(client),
            "X-CSRF-Token": token,
        }
        response = client.post("/ui/system/secrets/spotify_client_secret", headers=post_headers)
        _assert_html_response(response)
        assert "system-secret-card__status" in response.text
    client.app.dependency_overrides.pop(get_system_ui_service, None)
