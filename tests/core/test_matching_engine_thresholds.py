from __future__ import annotations

import pytest

from app.core.errors import InvalidInputError
from app.core.matching_engine import (
    calculate_slskd_match_confidence,
    compute_relevance_score,
    rank_candidates,
)
from app.core.types import ProviderAlbumDTO, ProviderArtistDTO, ProviderTrackDTO


def _artist(name: str, source: str = "spotify") -> ProviderArtistDTO:
    return ProviderArtistDTO(name=name, source=source)


def _track(
    *,
    title: str,
    artist: str,
    source_id: str,
    edition: tuple[str, ...] = (),
    album_title: str | None = None,
    year: int | None = None,
) -> ProviderTrackDTO:
    album = (
        ProviderAlbumDTO(title=album_title, source="spotify", edition_tags=edition, year=year)
        if album_title
        else None
    )
    return ProviderTrackDTO(
        title=title,
        artists=(_artist(artist),),
        album=album,
        source="spotify",
        source_id=source_id,
        year=year,
        edition_tags=edition,
    )


def test_rank_candidates_respects_thresholds() -> None:
    query = "Aurora - Runaway (Deluxe Edition) 2015"
    candidates = [
        _track(
            title="Runaway",
            artist="Aurora",
            source_id="a",
            edition=("deluxe",),
            album_title="Runaway (Deluxe Edition)",
            year=2015,
        ),
        _track(title="Runaway", artist="Aurora", source_id="b", album_title="Runaway", year=2015),
        _track(
            title="Runaway (Live)",
            artist="Aurora",
            source_id="c",
            edition=("live",),
            album_title="Runaway (Live)",
            year=2015,
        ),
        _track(title="Runaway", artist="Random", source_id="d", album_title="Runaway", year=2015),
    ]

    results = rank_candidates(
        query,
        candidates,
        min_artist_sim=0.6,
        complete_thr=0.65,
        nearly_thr=0.55,
        fuzzy_max=10,
        edition_aware=True,
    )

    ordering = [result.track.source_id for result in results]
    assert ordering[0] == "a"
    assert ordering[-1] == "d"
    assert results[0].confidence == "complete"
    assert results[0].score.total > results[1].score.total
    assert results[1].score.total > results[2].score.total
    assert results[-1].confidence in {"partial", "miss"}

    base_score = compute_relevance_score(
        "Runaway",
        {"title": "Runaway", "artists": ["Aurora"], "album": "Runaway", "type": "track"},
    )
    assert base_score > 0.6

    confidence = calculate_slskd_match_confidence(
        {
            "title": "Runaway",
            "artists": [{"name": "Aurora"}],
            "source": "spotify",
        },
        {
            "title": "Aurora - Runaway.mp3",
            "artist": "Aurora",
            "username": "aurora_fan",
            "bitrate_kbps": 320,
            "source": "slskd",
        },
    )
    assert 0.65 < confidence <= 1.0


def test_rank_candidates_rejects_empty_query() -> None:
    with pytest.raises(InvalidInputError):
        rank_candidates("", [])
