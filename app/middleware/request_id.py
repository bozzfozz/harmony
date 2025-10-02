"""Middleware for generating and propagating request identifiers."""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Ensure each request has a deterministic request identifier."""

    def __init__(self, app: ASGIApp, *, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming = request.headers.get(self._header_name, "").strip()
        request_id = incoming or str(uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        if self._header_name not in response.headers:
            response.headers[self._header_name] = request_id
        return response


__all__ = ["RequestIDMiddleware"]
