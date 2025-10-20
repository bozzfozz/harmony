from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.logging import APILoggingMiddleware


def test_ui_requests_emit_enriched_log_payload(caplog) -> None:
    app = FastAPI()

    @app.get("/ui/dashboard")
    def _ui_dashboard() -> dict[str, bool]:  # pragma: no cover - invoked via test client
        return {"ok": True}

    app.add_middleware(APILoggingMiddleware)
    client = TestClient(app)

    with caplog.at_level(logging.INFO):
        response = client.get("/ui/dashboard", headers={"User-Agent": "pytest-ui"})

    assert response.status_code == 200
    record = next(
        record for record in caplog.records if getattr(record, "event", "") == "api.request"
    )
    assert record.component == "ui"
    assert record.user_agent == "pytest-ui"
    assert record.path == "/ui/dashboard"
    assert record.method == "GET"
