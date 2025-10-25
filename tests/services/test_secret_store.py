from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db import run_session
from app.models import Setting
from app.services.secret_store import load_secret_store


@pytest.mark.asyncio
async def test_load_secret_store_reads_config_values() -> None:
    def _seed(session) -> None:
        session.add_all(
            [
                Setting(key="SLSKD_API_KEY", value="abc123"),
                Setting(key="SLSKD_URL", value="http://localhost:5030"),
            ]
        )
        session.commit()

    await run_session(_seed)

    store = await load_secret_store()

    record = store.secret_for_provider("slskd_api_key")
    assert record.value == "abc123"
    assert record.last4 == "c123"

    dependent = store.dependent_setting("slskd_api_key")
    assert dependent.value == "http://localhost:5030"


@pytest.mark.asyncio
async def test_load_secret_store_propagates_errors(monkeypatch) -> None:
    async def fake_run_session(func, *, factory=None):  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr("app.services.secret_store.run_session", fake_run_session)

    with pytest.raises(RuntimeError, match="boom"):
        await load_secret_store(session_factory=SimpleNamespace())
