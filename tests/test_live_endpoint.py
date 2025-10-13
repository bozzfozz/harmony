from __future__ import annotations

import asyncio

import pytest

from app.api import health as health_api
from app.main import live_probe


def test_api_health_live_is_lightweight() -> None:
    payload = asyncio.run(health_api.live())
    assert payload == {"status": "ok"}


def test_live_probe_forwards_to_health_router(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[dict[str, str]] = []

    async def _stub_live() -> dict[str, str]:
        payload = {"status": "ok"}
        called.append(payload)
        return payload

    monkeypatch.setattr(health_api, "live", _stub_live)

    payload = asyncio.run(live_probe())

    assert payload == {"status": "ok"}
    assert called == [{"status": "ok"}]
