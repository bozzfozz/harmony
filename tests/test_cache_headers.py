from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.dependencies import get_app_config
from app.main import app
from tests.helpers import api_path
from tests.simple_client import SimpleTestClient


def _lower_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def _parse_cache_control(value: str) -> dict[str, str | None]:
    directives: dict[str, str | None] = {}
    for part in value.split(","):
        key, _, remainder = part.strip().partition("=")
        directives[key] = remainder or None
    return directives


def _resolve_policy(pattern: str) -> tuple[int, int | None]:
    cache_config = get_app_config().middleware.cache
    ttl = cache_config.default_ttl
    stale = cache_config.stale_while_revalidate
    for rule in cache_config.cacheable_paths:
        if rule.pattern == pattern:
            if rule.ttl is not None:
                ttl = rule.ttl
            if rule.stale_while_revalidate is not None:
                stale = rule.stale_while_revalidate
            break
    return ttl, stale


def test_get_responses_emit_cache_headers_and_etag_roundtrip() -> None:
    path = api_path("")
    with SimpleTestClient(app) as client:
        first = client.get(path, use_raw_path=True)
        first_headers = _lower_headers(first.headers)
        assert first.status_code == 200
        assert "etag" in first_headers
        assert "last-modified" in first_headers
        assert "cache-control" in first_headers
        etag = first_headers["etag"]
        ttl, stale = _resolve_policy("^/$")
        directives = _parse_cache_control(first_headers["cache-control"])
        assert directives.get("public") is None or directives.get("public") == ""
        assert directives.get("max-age") == str(ttl)
        if stale is not None:
            assert directives.get("stale-while-revalidate") == str(stale)

        second = client.get(path, use_raw_path=True)
        second_headers = _lower_headers(second.headers)
        assert second.status_code == 200
        assert second_headers.get("etag") == etag
        assert "age" in second_headers
        assert second_headers.get("cache-control") == first_headers.get("cache-control")
        assert int(second_headers.get("age", "0")) <= ttl

        conditional = client.get(
            path, headers={"If-None-Match": etag}, use_raw_path=True
        )
        conditional_headers = _lower_headers(conditional.headers)
        assert conditional.status_code == 304
        assert conditional_headers.get("etag") == etag
        assert conditional_headers.get("last-modified") == first_headers.get(
            "last-modified"
        )
        assert conditional_headers.get("cache-control") == first_headers.get(
            "cache-control"
        )
        assert int(conditional_headers.get("age", "0")) <= ttl


def test_if_modified_since_returns_304_when_fresh() -> None:
    path = api_path("")
    with SimpleTestClient(app) as client:
        initial = client.get(path, use_raw_path=True)
        initial_headers = _lower_headers(initial.headers)
        assert initial.status_code == 200
        last_modified = initial_headers.get("last-modified")
        assert last_modified is not None

        conditional = client.get(
            path, headers={"If-Modified-Since": last_modified}, use_raw_path=True
        )
        assert conditional.status_code == 304

        # Invalid timestamps should be ignored and treated as a normal request
        invalid = client.get(
            path, headers={"If-Modified-Since": "not-a-date"}, use_raw_path=True
        )
        assert invalid.status_code == 200
        invalid_headers = _lower_headers(invalid.headers)
        assert "etag" in invalid_headers

        # Requests with an older timestamp should still return the fresh representation
        old_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )
        stale = client.get(
            path, headers={"If-Modified-Since": old_date}, use_raw_path=True
        )
        assert stale.status_code == 200


def test_head_responses_preserve_cache_metadata() -> None:
    path = api_path("")
    with SimpleTestClient(app) as client:
        initial = client.get(path, use_raw_path=True)
        initial_headers = _lower_headers(initial.headers)
        assert initial.status_code == 200
        etag = initial_headers.get("etag")
        assert etag is not None

        head_response = client.head(path, use_raw_path=True)
        head_headers = _lower_headers(head_response.headers)
        assert head_response.status_code == 200
        assert head_headers.get("etag") == etag
        assert head_response.text == ""

        conditional = client.head(
            path,
            headers={"If-None-Match": etag},
            use_raw_path=True,
        )
        conditional_headers = _lower_headers(conditional.headers)
        assert conditional.status_code == 304
        assert conditional_headers.get("etag") == etag


def test_activity_cache_policy_matches_configuration() -> None:
    path = api_path("activity")
    ttl, stale = _resolve_policy("^/activity$")
    with SimpleTestClient(app) as client:
        first = client.get(path, use_raw_path=True)
        first_headers = _lower_headers(first.headers)
        assert first.status_code == 200
        assert "etag" in first_headers
        directives = _parse_cache_control(first_headers["cache-control"])
        assert directives.get("max-age") == str(ttl)
        if stale is not None:
            assert directives.get("stale-while-revalidate") == str(stale)

        revalidation = client.get(
            path,
            headers={"If-None-Match": first_headers["etag"]},
            use_raw_path=True,
        )
        revalidation_headers = _lower_headers(revalidation.headers)
        assert revalidation.status_code == 304
        assert revalidation_headers.get("etag") == first_headers.get("etag")
        assert revalidation_headers.get("cache-control") == first_headers.get(
            "cache-control"
        )
        assert int(revalidation_headers.get("age", "0")) <= ttl
