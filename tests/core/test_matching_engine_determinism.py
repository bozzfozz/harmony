from __future__ import annotations

from random import shuffle

from app.core.matching_engine import rank_candidates
from app.core.types import ProviderArtistDTO, ProviderTrackDTO


def _make_track(identifier: str, title: str, artist: str) -> ProviderTrackDTO:
    return ProviderTrackDTO(
        title=title,
        artists=(ProviderArtistDTO(name=artist, source="test"),),
        source="test",
        source_id=identifier,
    )


def test_rank_candidates_is_deterministic() -> None:
    query = "Artist - Favourite"
    candidates = [
        _make_track("1", "Favourite", "Artist"),
        _make_track("2", "Favourite", "Other"),
        _make_track("3", "Favourite (Acoustic)", "Artist"),
        _make_track("4", "Another Song", "Artist"),
    ]

    baseline = [
        result.track.source_id for result in rank_candidates(query, candidates, fuzzy_max=10)
    ]

    for _ in range(5):
        shuffled = list(candidates)
        shuffle(shuffled)
        order = [
            result.track.source_id for result in rank_candidates(query, shuffled, fuzzy_max=10)
        ]
        assert order == baseline

    limited = rank_candidates(query, candidates, fuzzy_max=2)
    assert len(limited) == 2
    assert limited[0].score.total >= limited[1].score.total
    assert all(result.track.source_id in {"1", "3"} for result in limited)
