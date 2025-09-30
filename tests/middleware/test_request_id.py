from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.middleware.request_id import RequestIDMiddleware


def create_app() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/state")
    async def read_state(request: Request) -> dict[str, str]:
        return {"request_id": request.state.request_id}

    return TestClient(app)


def test_request_id_header_passthrough_and_generation() -> None:
    client = create_app()

    custom_id = "abc-123"
    response = client.get("/state", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.json()["request_id"] == custom_id
    assert response.headers["X-Request-ID"] == custom_id

    generated_response = client.get("/state")
    assert generated_response.status_code == 200
    generated_id = generated_response.json()["request_id"]
    assert generated_id
    uuid.UUID(generated_id)
    assert generated_response.headers["X-Request-ID"] == generated_id
