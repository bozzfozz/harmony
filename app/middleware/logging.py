"""Structured API request logging middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import time
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.logging import get_logger

from . import request_logging


class APILoggingMiddleware(BaseHTTPMiddleware):
    """Emit structured request/response events following the logging contract."""

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
        error: BaseException | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except BaseException as exc:  # pragma: no cover - exercised via tests
            error = self._unwrap_exception(exc)
            handler = self._lookup_exception_handler(request, error)
            if handler is None:
                raise exc
            response = await handler(request, error)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            payload: dict[str, Any] = {
                "component": self._component,
                "status": "ok" if status_code < 400 else "error",
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": round(duration_ms, 3),
                "entity_id": getattr(request.state, "request_id", None),
            }
            if error is not None:
                payload["error"] = error.__class__.__name__
            log_event(self._logger, "api.request", **payload)

            if response is not None:
                request_id = getattr(request.state, "request_id", None)
                if request_id and "X-Request-ID" not in response.headers:
                    response.headers["X-Request-ID"] = request_id

    def _unwrap_exception(self, exc: BaseException) -> BaseException:
        current = exc
        seen: set[int] = set()
        while True:
            if id(current) in seen:
                break
            seen.add(id(current))
            members = getattr(current, "exceptions", None)
            if not members:
                break
            first = members[0]
            if not isinstance(first, BaseException):
                break
            current = first
        return current

    def _lookup_exception_handler(
        self, request: Request, exc: BaseException
    ) -> Callable[[Request, BaseException], Awaitable[Response]] | None:
        handlers = getattr(request.app, "exception_handlers", {})
        for cls in type(exc).__mro__:
            handler = handlers.get(cls)
            if handler is not None:
                return handler  # type: ignore[return-value]
        return handlers.get(None)  # type: ignore[return-value]


__all__ = ["APILoggingMiddleware"]


def log_event(logger: Any, event: str, /, **payload: Any) -> None:
    """Proxy to ``request_logging.log_event`` for compatibility."""

    request_logging.log_event(logger, event, **payload)
