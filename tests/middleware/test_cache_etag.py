from datetime import datetime, timezone
from email.utils import format_datetime

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.config import load_config
from app.middleware.cache import CacheMiddleware
from app.services.cache import ResponseCache


def _etag_values(header: str | None) -> set[str]:
    if not header:
        return set()
    return {segment.strip() for segment in header.split(",") if segment.strip()}


@pytest.fixture
def _cache_env(monkeypatch: pytest.MonkeyPatch) -> None:
    relevant_keys = {
        "CACHE_DEFAULT_TTL_S",
        "CACHE_STALE_WHILE_REVALIDATE_S",
        "CACHE_FAIL_OPEN",
        "CACHE_ENABLED",
        "CACHE_MAX_ITEMS",
        "CACHE_STRATEGY_ETAG",
        "CACHEABLE_PATHS",
        "CACHE_WRITE_THROUGH",
        "CACHE_LOG_EVICTIONS",
        "DATABASE_URL",
    }
    for key in relevant_keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/harmony"
    )
    monkeypatch.setenv("CACHEABLE_PATHS", "^/etag$|60|")


def _create_client() -> tuple[TestClient, dict[str, int]]:
    config = load_config()
    cache_config = config.middleware.cache
    app = FastAPI()
    app.state.api_base_path = config.api_base_path

    call_counts: dict[str, int] = {"/etag": 0}
    last_modified = format_datetime(datetime(2024, 1, 1, tzinfo=timezone.utc), usegmt=True)

    @app.get("/etag")
    def _etag_route() -> JSONResponse:
        call_counts["/etag"] += 1
        response = JSONResponse({"invocations": call_counts["/etag"]})
        response.headers["ETag"] = '"static-etag"'
        response.headers["Last-Modified"] = last_modified
        return response

    response_cache = ResponseCache(
        max_items=cache_config.max_items,
        default_ttl=float(cache_config.default_ttl),
        fail_open=cache_config.fail_open,
        write_through=cache_config.write_through,
        log_evictions=cache_config.log_evictions,
    )
    app.state.response_cache = response_cache
    app.add_middleware(CacheMiddleware, cache=response_cache, config=cache_config)

    return TestClient(app), call_counts


@pytest.mark.usefixtures("_cache_env")
def test_custom_etag_respected_and_304_returned() -> None:
    client, counts = _create_client()

    first = client.get("/etag")
    assert first.status_code == 200
    assert _etag_values(first.headers.get("ETag")) == {'"static-etag"'}
    assert counts["/etag"] == 1

    cached = client.get("/etag")
    assert cached.status_code == 200
    assert _etag_values(cached.headers.get("ETag")) == {'"static-etag"'}
    assert counts["/etag"] == 1

    conditional = client.get("/etag", headers={"If-None-Match": '"static-etag"'})
    assert conditional.status_code == 304
    assert _etag_values(conditional.headers.get("ETag")) == {'"static-etag"'}
    assert counts["/etag"] == 1
