from __future__ import annotations

from typing import Any, Mapping

import pytest

from app.config import MatchingConfig
from app.core.errors import InvalidInputError
from app.core.matching_engine import (
    MusicMatchingEngine,
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
    album_total: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ProviderTrackDTO:
    album = (
        ProviderAlbumDTO(
            title=album_title,
            source="spotify",
            edition_tags=edition,
            year=year,
            total_tracks=album_total,
        )
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
        metadata=metadata or {},
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
        _track(
            title="Runaway",
            artist="Aurora",
            source_id="b",
            album_title="Runaway",
            year=2015,
        ),
        _track(
            title="Runaway (Live)",
            artist="Aurora",
            source_id="c",
            edition=("live",),
            album_title="Runaway (Live)",
            year=2015,
        ),
        _track(
            title="Runaway",
            artist="Random",
            source_id="d",
            album_title="Runaway",
            year=2015,
        ),
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
    assert results[-1].confidence == "incomplete"

    base_score = compute_relevance_score(
        "Runaway",
        {
            "title": "Runaway",
            "artists": ["Aurora"],
            "album": "Runaway",
            "type": "track",
        },
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


def test_calculate_album_completion_applies_thresholds() -> None:
    engine = MusicMatchingEngine(
        config=MatchingConfig(
            edition_aware=True,
            fuzzy_max_candidates=50,
            min_artist_similarity=0.6,
            complete_threshold=0.65,
            nearly_threshold=0.55,
        )
    )
    base_tracks = [
        _track(
            title=f"Track {idx}",
            artist="Aurora",
            source_id=str(idx),
            album_title="Runaway",
            year=2015,
            metadata={"track_number": idx},
        )
        for idx in range(1, 5)
    ]

    ratio_incomplete, label_incomplete = engine.calculate_album_completion(
        base_tracks[:2], expected_total_tracks=5
    )
    assert ratio_incomplete == 0.4
    assert label_incomplete == "incomplete"

    ratio_nearly, label_nearly = engine.calculate_album_completion(
        base_tracks[:3], expected_total_tracks=5
    )
    assert ratio_nearly == 0.6
    assert label_nearly == "nearly"

    ratio_complete, label_complete = engine.calculate_album_completion(
        base_tracks, expected_total_tracks=6
    )
    assert ratio_complete == pytest.approx(0.6667)
    assert label_complete == "complete"


def test_calculate_album_completion_infers_expected_total_from_tracks() -> None:
    engine = MusicMatchingEngine(
        config=MatchingConfig(
            edition_aware=True,
            fuzzy_max_candidates=50,
            min_artist_similarity=0.6,
            complete_threshold=0.65,
            nearly_threshold=0.55,
        )
    )
    tracks = [
        _track(
            title="Runaway",
            artist="Aurora",
            source_id="a",
            album_title="Runaway",
            year=2015,
            album_total=10,
            metadata={"track_number": 1},
        ),
        _track(
            title="Running With the Wolves",
            artist="Aurora",
            source_id="b",
            album_title="Runaway",
            year=2015,
            album_total=10,
            metadata={"track_number": 2},
        ),
        _track(
            title="Conqueror",
            artist="Aurora",
            source_id="c",
            album_title="Runaway",
            year=2015,
            album_total=10,
            metadata={"track_number": 2},
        ),
    ]

    ratio, label = engine.calculate_album_completion(tracks)
    assert ratio == 0.2
    assert label == "incomplete"
