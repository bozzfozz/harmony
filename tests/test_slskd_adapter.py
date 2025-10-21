"""Tests for the Soulseek (slskd) adapter helpers."""

from __future__ import annotations

import pytest

from app.integrations.base import TrackCandidate
from app.integrations.slskd_adapter import (
    _build_candidate,
    _iter_files,
    _parse_retry_after_ms,
    _sort_candidates,
)


def _candidate(
    *,
    title: str,
    bitrate: int | None,
    seeders: int = 1,
    size: int = 1_000_000,
    format_name: str = "MP3",
) -> TrackCandidate:
    return TrackCandidate(
        title=title,
        artist=None,
        format=format_name,
        bitrate_kbps=bitrate,
        size_bytes=size,
        seeders=seeders,
        username=None,
        availability=None,
        source="slskd",
        download_uri=None,
    )


def test_sort_candidates_prefers_higher_bitrate_when_other_factors_equal() -> None:
    ranking = {"MP3": 0}
    low = _candidate(title="low", bitrate=128)
    mid = _candidate(title="mid", bitrate=192)
    high = _candidate(title="high", bitrate=320)

    ranked = _sort_candidates([low, high, mid], ranking)

    assert [candidate.title for candidate in ranked] == ["high", "mid", "low"]


def test_sort_candidates_handles_missing_bitrate() -> None:
    ranking = {"MP3": 0}
    missing = _candidate(title="missing", bitrate=None)
    with_bitrate = _candidate(title="with", bitrate=256)

    ranked = _sort_candidates([missing, with_bitrate], ranking)

    assert [candidate.title for candidate in ranked] == ["with", "missing"]


def test_sort_candidates_preserves_seeder_priority_over_bitrate() -> None:
    ranking = {"MP3": 0}
    more_seeders = _candidate(title="more_seeders", bitrate=128, seeders=10)
    higher_bitrate = _candidate(title="higher_bitrate", bitrate=320, seeders=2)

    ranked = _sort_candidates([higher_bitrate, more_seeders], ranking)

    assert [candidate.title for candidate in ranked] == ["more_seeders", "higher_bitrate"]


def test_iter_files_enriches_username_and_traverses_nested_payloads() -> None:
    payload = {
        "results": [
            {
                "username": "alice",
                "files": [
                    {"filename": "track-one.mp3", "bitrate": 320},
                    {"filename": "track-two.flac", "bitrate": 1000, "username": "bob"},
                ],
            }
        ]
    }

    files = list(_iter_files(payload))

    assert files[0]["filename"] == "track-one.mp3"
    assert files[0]["username"] == "alice"
    assert files[1]["filename"] == "track-two.flac"
    assert files[1]["username"] == "bob"


def test_iter_files_handles_mixed_collections_and_plain_entries() -> None:
    payload = [
        {"matches": {"files": [{"filename": "one.ogg"}]}},
        {"tracks": [{"user": "carol", "files": {"filename": "two.wav"}}]},
        {"filename": "three.mp3", "bitrate": 256},
    ]

    files = list(_iter_files(payload))

    filenames = {item["filename"] for item in files}

    assert filenames == {"one.ogg", "two.wav", "three.mp3"}
    usernames = {item.get("username") for item in files}
    assert "carol" in usernames


def test_build_candidate_normalizes_and_enriches_metadata() -> None:
    entry = {
        "title": "Song Title",
        "artist": "Artist Name",
        "filename": "Artist - Song Title.flac",
        "bitrate": "256",
        "size": "4096",
        "seeders": "3",
        "user": "dj",
        "album": "Album Name",
        "genres": ["Rock", ""],
        "year": "2001",
        "path": "/music/song.flac",
    }

    candidate = _build_candidate(entry)

    assert candidate.title == "Song Title"
    assert candidate.artist == "Artist Name"
    assert candidate.format == "FLAC"
    assert candidate.bitrate_kbps == 256
    assert candidate.size_bytes == 4096
    assert candidate.seeders == 3
    assert candidate.username == "dj"
    assert candidate.availability == pytest.approx(0.6)
    assert candidate.download_uri == "/music/song.flac"
    assert candidate.metadata["filename"] == "Artist - Song Title.flac"
    assert "genres" in candidate.metadata
    assert candidate.metadata["year"] == 2001


@pytest.mark.parametrize(
    "headers, expected",
    [
        ({"Retry-After": "120"}, 120_000),
        ({"Retry-After": "-5"}, 0),
        ({"Retry-After": "soon"}, None),
        ({}, None),
    ],
)
def test_parse_retry_after_ms(headers: dict[str, str], expected: int | None) -> None:
    assert _parse_retry_after_ms(headers) == expected
