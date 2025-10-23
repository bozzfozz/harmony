from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import override_runtime_env
from app.dependencies import get_app_config
from app.main import app

pytestmark = pytest.mark.anyio


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@dataclass(slots=True)
class UiRouteExpectation:
    path: str
    title: str
    markers: tuple[str, ...]


@pytest.fixture()
async def async_ui_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("HARMONY_API_KEYS", "primary-key")
    monkeypatch.setenv("UI_ROLE_DEFAULT", "operator")
    monkeypatch.setenv("UI_ROLE_OVERRIDES", "")
    monkeypatch.setenv("UI_FEATURE_SPOTIFY", "true")
    monkeypatch.setenv("UI_FEATURE_SOULSEEK", "true")
    monkeypatch.setenv("UI_FEATURE_DLQ", "true")
    monkeypatch.setenv("UI_FEATURE_IMPORTS", "true")

    override_runtime_env(None)
    get_app_config.cache_clear()

    transport = ASGITransport(app=app)

    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        await transport.aclose()
        override_runtime_env(None)
        get_app_config.cache_clear()


@pytest.fixture()
async def logged_in_async_client(
    async_ui_client: AsyncClient,
) -> AsyncIterator[AsyncClient]:
    response = await async_ui_client.post(
        "/ui/login",
        data={"api_key": "primary-key"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert async_ui_client.cookies.get("ui_session") is not None
    assert async_ui_client.cookies.get("csrftoken") is not None
    cookie_header = "; ".join(
        f"{name}={value}" for name, value in async_ui_client.cookies.items()
    )
    async_ui_client.headers.setdefault("Cookie", cookie_header)
    yield async_ui_client


_ROUTE_EXPECTATIONS: tuple[UiRouteExpectation, ...] = (
    UiRouteExpectation(
        path="/ui/",
        title="Dashboard · Harmony Operator Console",
        markers=(
            'data-role="operator"',
            'data-fragment="dashboard-status"',
            'data-test="nav-home"',
        ),
    ),
    UiRouteExpectation(
        path="/ui/downloads",
        title="Downloads · Harmony Operator Console",
        markers=(
            'data-fragment="downloads-table"',
            'data-test="nav-operator"',
        ),
    ),
    UiRouteExpectation(
        path="/ui/jobs",
        title="Jobs · Harmony Operator Console",
        markers=(
            'data-fragment="jobs-table"',
            'data-test="nav-operator"',
        ),
    ),
    UiRouteExpectation(
        path="/ui/watchlist",
        title="Watchlist · Harmony Operator Console",
        markers=(
            'data-fragment="watchlist-table"',
            'data-test="nav-operator"',
        ),
    ),
    UiRouteExpectation(
        path="/ui/activity",
        title="Activity · Harmony Operator Console",
        markers=(
            'data-fragment="activity-table"',
            'data-test="nav-operator"',
        ),
    ),
    UiRouteExpectation(
        path="/ui/spotify",
        title="Spotify · Harmony Operator Console",
        markers=(
            'data-fragment="spotify-status"',
            'data-test="nav-spotify"',
        ),
    ),
    UiRouteExpectation(
        path="/ui/system",
        title="System diagnostics · Harmony Operator Console",
        markers=(
            'data-fragment="system-liveness"',
            'data-test="nav-home"',
        ),
    ),
    UiRouteExpectation(
        path="/ui/operations",
        title="Operations · Harmony Operator Console",
        markers=(
            'data-fragment="operations-downloads"',
            'data-test="nav-operator"',
        ),
    ),
)


@pytest.mark.parametrize(
    "expectation",
    _ROUTE_EXPECTATIONS,
    ids=[expectation.path for expectation in _ROUTE_EXPECTATIONS],
)
async def test_ui_routes_render_expected_html(
    expectation: UiRouteExpectation,
    logged_in_async_client: AsyncClient,
) -> None:
    response = await logged_in_async_client.get(expectation.path)
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "").lower()
    assert "text/html" in content_type
    body = response.text
    assert expectation.title in body
    for marker in expectation.markers:
        assert marker in body
