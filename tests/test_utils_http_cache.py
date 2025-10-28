from __future__ import annotations

from datetime import UTC, datetime
import hashlib

from fastapi import Request
import pytest

from app.utils.http_cache import (
    compute_playlist_collection_metadata,
    format_http_datetime,
    is_request_not_modified,
)


class _StubPlaylist:
    def __init__(self, updated_at: datetime | None) -> None:
        self.updated_at = updated_at


def _make_request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in headers.items()
        ],
    }
    return Request(scope)


@pytest.mark.parametrize(
    "playlists,filters_hash,expected_etag,expected_last_modified",
    [
        (
            [],
            None,
            '"pl-v1-8a47324de901578af6a874f9fa853712c5bff8ab:0"',
            datetime(1970, 1, 1, tzinfo=UTC),
        ),
        (
            [
                _StubPlaylist(datetime(2023, 5, 4, 10, 30, 0)),
                _StubPlaylist(datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)),
            ],
            None,
            '"pl-v1-faf606caf04de19af35146f350dddf59897ed598:2"',
            datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        ),
        (
            [_StubPlaylist(None)],
            "abc",
            lambda latest: '"pl-v1-{}:1"'.format(
                hashlib.sha1(f"playlists|v1|abc|1|{latest.isoformat()}".encode()).hexdigest()
            ),
            datetime(1970, 1, 1, tzinfo=UTC),
        ),
    ],
)
def test_compute_playlist_collection_metadata(
    playlists, filters_hash, expected_etag, expected_last_modified
):
    metadata = compute_playlist_collection_metadata(playlists, filters_hash=filters_hash)

    if callable(expected_etag):
        expected_etag = expected_etag(expected_last_modified)

    assert metadata.etag == expected_etag
    assert metadata.last_modified == expected_last_modified
    assert format_http_datetime(metadata.last_modified).endswith("GMT")


def test_is_request_not_modified_accepts_weak_validator():
    etag = '"pl-v1-weak:1"'
    request = _make_request({"if-none-match": f"W/{etag}"})

    assert is_request_not_modified(request, etag=etag, last_modified=None)


def test_is_request_not_modified_accepts_wildcard():
    etag = '"pl-v1-any:2"'
    request = _make_request({"if-none-match": "*"})

    assert is_request_not_modified(request, etag=etag, last_modified=None)


def test_is_request_not_modified_rejects_non_matching_etag():
    etag = '"pl-v1-target:3"'
    request = _make_request({"if-none-match": '"other"'})

    assert not is_request_not_modified(request, etag=etag, last_modified=None)


def test_is_request_not_modified_ignores_subsecond_last_modified():
    last_modified = datetime(2024, 5, 1, 12, 30, 0, 500000, tzinfo=UTC)
    header_value = format_http_datetime(last_modified)
    request = _make_request({"if-modified-since": header_value})

    assert is_request_not_modified(request, etag=None, last_modified=last_modified)
