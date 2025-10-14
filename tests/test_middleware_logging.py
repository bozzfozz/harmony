from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.middleware.logging import APILoggingMiddleware


class _CustomError(Exception):
    """Sentinel exception used for testing the logging middleware."""


def test_api_logging_middleware_handles_sync_exception_handlers() -> None:
    app = FastAPI()

    @app.exception_handler(_CustomError)
    def _handle_custom(
        _: Request, exc: _CustomError
    ) -> JSONResponse:  # pragma: no cover - invoked via test client
        return JSONResponse({"message": "boom", "exc": exc.__class__.__name__}, status_code=418)

    @app.get("/boom")
    def _boom() -> None:  # pragma: no cover - invoked via test client
        raise _CustomError()

    app.add_middleware(APILoggingMiddleware)
    client = TestClient(app)

    response = client.get("/boom")

    assert response.status_code == 418
    assert response.json() == {"message": "boom", "exc": "_CustomError"}
