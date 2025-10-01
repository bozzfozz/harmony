"""Middleware emitting structured API request logs."""

from __future__ import annotations

import time
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.logging import get_logger
from app.logging_events import log_event


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Capture request timing information and emit ``api.request`` events."""

    def __init__(self, app: ASGIApp, *, component: str = "api") -> None:
        super().__init__(app)
        self._logger = get_logger(__name__)
        self._component = component

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        status_code = 500
        response: Response | None = None
        error: Exception | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            error = exc
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            status = "ok" if status_code < 400 else "error"
            payload: dict[str, Any] = {
                "component": self._component,
                "status": status,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": round(duration_ms, 3),
                "entity_id": getattr(request.state, "request_id", None),
            }
            if error is not None:
                payload["error"] = error.__class__.__name__
            if request.url.query:
                payload.setdefault("meta", {})
                payload["meta"]["query_params"] = True
            log_event(self._logger, "api.request", **payload)
            # Ensure response headers propagate request id even when logging occurs
            if response is not None and hasattr(response, "headers"):
                request_id = getattr(request.state, "request_id", None)
                if request_id and "X-Request-ID" not in response.headers:
                    response.headers["X-Request-ID"] = request_id


__all__ = ["RequestLoggingMiddleware"]
