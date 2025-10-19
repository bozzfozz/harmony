from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
import app.main as app_main


def test_soulseek_client_closed_on_shutdown(monkeypatch) -> None:
    mock_client = SimpleNamespace(close=AsyncMock())

    def _get_client() -> SimpleNamespace:
        return mock_client

    monkeypatch.setattr(app_main, "get_soulseek_client", _get_client)

    with TestClient(app):
        pass

    assert mock_client.close.await_count == 1
