"""Tests for the Soulseek (slskd) adapter helpers."""

from __future__ import annotations

from app.integrations.base import TrackCandidate
from app.integrations.slskd_adapter import _sort_candidates


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
