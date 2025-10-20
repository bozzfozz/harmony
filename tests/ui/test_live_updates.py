import json

from fastapi.testclient import TestClient
import pytest

from app.ui.router import _LiveFragmentBuilder, _ui_event_stream
from tests.ui.test_operations_pages import _cookies_header
from tests.ui.test_ui_auth import _create_client


def _login(client: TestClient, api_key: str = "primary-key") -> None:
    response = client.post("/ui/login", data={"api_key": api_key}, follow_redirects=False)
    assert response.status_code == 303


def test_ui_events_disabled_without_flag(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/events", headers=headers)
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_ui_event_stream_emits_payload() -> None:
    async def _build_payload() -> dict[str, object]:
        return {
            "fragment_id": "hx-downloads-table",
            "event": "downloads",
            "html": '<div id="hx-downloads-table"></div>',
            "data_attributes": {"limit": "20", "offset": "0"},
        }

    builder = _LiveFragmentBuilder(name="downloads", interval=0.1, build=_build_payload)

    class _StubRequest:
        def __init__(self) -> None:
            self.cookies = {}
            self._calls = 0

        async def is_disconnected(self) -> bool:
            self._calls += 1
            return self._calls > 1

    request = _StubRequest()
    stream = _ui_event_stream(request, [builder])
    chunk = None
    async for chunk in stream:
        break

    assert chunk is not None
    assert "event: fragment" in chunk
    assert "hx-downloads-table" in chunk
