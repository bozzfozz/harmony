from __future__ import annotations

from datetime import UTC, datetime

from starlette.requests import Request

from app.ui.context import build_dashboard_page_context, build_login_page_context
from app.ui.router import templates
from app.ui.session import UiFeatures, UiSession


def _make_request(path: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
    }
    return Request(scope)


def test_login_template_renders_error_and_form() -> None:
    request = _make_request("/ui/login")
    context = build_login_page_context(request, error="Invalid key")
    template = templates.get_template("pages/login.j2")
    html = template.render(**context)

    assert "Harmony Operator Console" in html
    assert "Invalid key" in html
    assert "id=\"login-form\"" in html
    assert "data-role=\"anonymous\"" in html
    assert "nav-home" not in html


def test_dashboard_template_renders_navigation_and_features() -> None:
    request = _make_request("/ui")
    features = UiFeatures(spotify=True, soulseek=False, dlq=True, imports=False)
    now = datetime.now(tz=UTC)
    session = UiSession(
        identifier="session-1",
        role="admin",
        features=features,
        fingerprint="fp",
        issued_at=now,
        last_seen_at=now,
    )
    context = build_dashboard_page_context(
        request,
        session=session,
        csrf_token="csrf-token-value",
    )
    template = templates.get_template("pages/dashboard.j2")
    html = template.render(**context)

    assert "meta name=\"csrf-token\" content=\"csrf-token-value\"" in html
    assert "nav-home" in html
    assert "nav-operator" in html
    assert "nav-admin" in html
    assert "id=\"features-table\"" in html
    assert "status-badge--success" in html
    assert "status-badge--muted" in html
    assert "operator-action" in html
    assert "admin-action" in html
    assert "Welcome" in html
    assert "Current role: Admin" in html
