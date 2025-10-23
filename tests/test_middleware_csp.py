from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import importlib
import os

from fastapi.testclient import TestClient

from app.config import override_runtime_env

_BASELINE_DIRECTIVES = (
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "connect-src 'self'",
    "font-src 'self'",
    "frame-ancestors 'none'",
)
_HTMX_CDN_ORIGIN = "https://unpkg.com/htmx.org"


@contextmanager
def _ui_client(env_override: dict[str, str] | None = None) -> Iterator[TestClient]:
    module = importlib.import_module("app.main")
    overrides = env_override or {}
    previous_env = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        override_runtime_env(dict(os.environ))
        module = importlib.reload(module)
        with TestClient(module.app) as client:
            yield client
    finally:
        override_runtime_env(None)
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        module = importlib.reload(module)


def test_ui_responses_include_baseline_csp_header() -> None:
    with _ui_client() as client:
        response = client.get("/ui/", follow_redirects=False)
        assert response.status_code in {200, 302, 303, 401}
        header = response.headers.get("content-security-policy")
        assert header is not None
        for directive in _BASELINE_DIRECTIVES:
            assert directive in header


def test_ui_csp_allows_htmx_cdn_when_enabled() -> None:
    with _ui_client({"UI_ALLOW_CDN": "true"}) as client:
        response = client.get("/ui/", follow_redirects=False)
        assert response.status_code in {200, 302, 303, 401}
        header = response.headers.get("content-security-policy")
        assert header is not None
        assert "script-src 'self'" in header
        assert _HTMX_CDN_ORIGIN in header
