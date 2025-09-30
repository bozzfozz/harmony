"""Middleware that ensures every request has a request id."""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Populate ``request.state.request_id`` for downstream handlers."""

    header_name = "X-Request-ID"

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:  # type: ignore[override]
        incoming = request.headers.get(self.header_name, "").strip()
        request_id = incoming or str(uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        if self.header_name not in response.headers:
            response.headers[self.header_name] = request_id
        return response


__all__ = ["RequestIDMiddleware"]
