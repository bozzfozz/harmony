"""Content Security Policy middleware aligned with ``docs/ui/csp.md``."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

_BASELINE_DIRECTIVES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("default-src", ("'self'",)),
    ("script-src", ("'self'",)),
    ("style-src", ("'self'", "'unsafe-inline'")),
    ("img-src", ("'self'", "data:")),
    ("connect-src", ("'self'",)),
    ("font-src", ("'self'",)),
    ("frame-ancestors", ("'none'",)),
)
_HTMX_CDN_ORIGIN: Final[str] = "https://unpkg.com/htmx.org"


def _deduplicate(values: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        if value not in seen:
            seen[value] = None
    return tuple(seen.keys())


def _build_directives(*, allow_script_cdn: bool) -> tuple[tuple[str, tuple[str, ...]], ...]:
    directives: list[tuple[str, tuple[str, ...]]] = []
    for name, values in _BASELINE_DIRECTIVES:
        if name == "script-src" and allow_script_cdn:
            extended = _deduplicate((*values, _HTMX_CDN_ORIGIN))
            directives.append((name, extended))
            continue
        directives.append((name, values))
    return tuple(directives)


def _serialize_directives(directives: Sequence[tuple[str, Sequence[str]]]) -> str:
    segments: list[str] = []
    for name, values in directives:
        if not values:
            continue
        joined = " ".join(values)
        segments.append(f"{name} {joined};")
    return " ".join(segments)


class ContentSecurityPolicyMiddleware(BaseHTTPMiddleware):
    """Attach a strict Content Security Policy header to every response."""

    def __init__(self, app: ASGIApp, *, allow_script_cdn: bool = False) -> None:
        super().__init__(app)
        directives = _build_directives(allow_script_cdn=allow_script_cdn)
        self._policy = _serialize_directives(directives)

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", self._policy)
        return response


__all__ = ["ContentSecurityPolicyMiddleware"]
