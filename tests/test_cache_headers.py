from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.main import app
from tests.helpers import api_path
from tests.simple_client import SimpleTestClient


def _lower_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


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

        second = client.get(path, use_raw_path=True)
        second_headers = _lower_headers(second.headers)
        assert second.status_code == 200
        assert second_headers.get("etag") == etag
        assert "age" in second_headers
        assert second_headers.get("cache-control") == first_headers.get("cache-control")

        conditional = client.get(path, headers={"If-None-Match": etag}, use_raw_path=True)
        conditional_headers = _lower_headers(conditional.headers)
        assert conditional.status_code == 304
        assert conditional_headers.get("etag") == etag
        assert conditional_headers.get("last-modified") == first_headers.get("last-modified")
        assert conditional_headers.get("cache-control") == first_headers.get("cache-control")


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
        invalid = client.get(path, headers={"If-Modified-Since": "not-a-date"}, use_raw_path=True)
        assert invalid.status_code == 200
        invalid_headers = _lower_headers(invalid.headers)
        assert "etag" in invalid_headers

        # Requests with an older timestamp should still return the fresh representation
        old_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )
        stale = client.get(path, headers={"If-Modified-Since": old_date}, use_raw_path=True)
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
