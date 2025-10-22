from __future__ import annotations

from collections.abc import Callable
from types import MethodType
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.ui.services import ActivityPage, ActivityUiService, get_activity_ui_service
from tests.ui.test_ui_auth import _assert_html_response, _create_client


def _cookies_header(client: TestClient) -> str:
    return "; ".join(f"{name}={value}" for name, value in client.cookies.items())


def _login(client: TestClient, api_key: str = "primary-key") -> None:
    response = client.post("/ui/login", data={"api_key": api_key}, follow_redirects=False)
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_activity_service_async_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ActivityUiService()

    def _fake_list_activity(
        self: ActivityUiService,
        *,
        limit: int,
        offset: int,
        type_filter: str | None,
        status_filter: str | None,
    ) -> ActivityPage:
        return ActivityPage(
            items=(),
            limit=limit,
            offset=offset,
            total_count=42,
            type_filter=type_filter,
            status_filter=status_filter,
        )

    service.list_activity = MethodType(_fake_list_activity, service)

    captured: dict[str, object] = {}

    async def _capture_to_thread(
        func: Callable[..., ActivityPage],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> ActivityPage:
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return func(*args, **kwargs)

    monkeypatch.setattr("app.ui.services.activity.asyncio.to_thread", _capture_to_thread)

    page = await service.list_activity_async(
        limit=5,
        offset=10,
        type_filter="test",
        status_filter="ok",
    )

    assert isinstance(page, ActivityPage)
    assert page.limit == 5
    assert page.offset == 10
    assert page.type_filter == "test"
    assert page.status_filter == "ok"

    func = captured.get("func")
    assert func is service.list_activity
    assert captured.get("kwargs") == {
        "limit": 5,
        "offset": 10,
        "type_filter": "test",
        "status_filter": "ok",
    }


class _AsyncOnlyActivityService:
    def __init__(self) -> None:
        self.async_calls: list[tuple[int, int, str | None, str | None]] = []

    def list_activity(
        self,
        *,
        limit: int,
        offset: int,
        type_filter: str | None,
        status_filter: str | None,
    ) -> ActivityPage:
        raise AssertionError("synchronous list_activity should not be used")

    async def list_activity_async(
        self,
        *,
        limit: int,
        offset: int,
        type_filter: str | None,
        status_filter: str | None,
    ) -> ActivityPage:
        self.async_calls.append((limit, offset, type_filter, status_filter))
        return ActivityPage(
            items=(),
            limit=limit,
            offset=offset,
            total_count=0,
            type_filter=type_filter,
            status_filter=status_filter,
        )


def test_activity_table_uses_async_service(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _AsyncOnlyActivityService()
    app.dependency_overrides[get_activity_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get("/ui/activity/table", headers=headers)
            _assert_html_response(response)
    finally:
        app.dependency_overrides.pop(get_activity_ui_service, None)

    assert stub.async_calls == [(50, 0, None, None)]


def test_activity_page_renders_polling_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/activity", headers=headers)
        _assert_html_response(response)

    html = response.text
    assert 'hx-trigger="load, every 60s"' in html
    assert 'data-fragment="activity-table"' in html
