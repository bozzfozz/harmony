"""Tests for the Content Security Policy middleware."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.csp import ContentSecurityPolicyMiddleware


_HTMX_CDN = "https://unpkg.com/htmx.org"


def create_app(*, allow_script_cdn: bool = False) -> FastAPI:
    app = FastAPI()

    @app.get("/")
    async def read_root() -> Mapping[str, str]:
        return {"status": "ok"}

    app.add_middleware(
        ContentSecurityPolicyMiddleware,
        allow_script_cdn=allow_script_cdn,
    )
    return app


def parse_csp(header: str) -> dict[str, tuple[str, ...]]:
    directives: dict[str, tuple[str, ...]] = {}
    for segment in header.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        parts = segment.split()
        name, *values = parts
        directives[name] = tuple(values)
    return directives


def test_default_policy_has_only_self_script_directive() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    header = response.headers["Content-Security-Policy"]
    directives = parse_csp(header)

    assert directives["script-src"] == ("'self'",)
    assert _HTMX_CDN not in directives["script-src"]


def test_cdn_flag_appends_htmx_origin() -> None:
    app = create_app(allow_script_cdn=True)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    header = response.headers["Content-Security-Policy"]
    directives = parse_csp(header)

    assert directives["script-src"] == ("'self'", _HTMX_CDN)


def test_multiple_requests_keep_policy_stable() -> None:
    app = create_app(allow_script_cdn=True)

    with TestClient(app) as client:
        headers = [
            client.get("/").headers["Content-Security-Policy"]
            for _ in range(3)
        ]

    assert headers[0] == headers[1] == headers[2]
