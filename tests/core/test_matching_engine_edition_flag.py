from __future__ import annotations

from app.core.matching_engine import rank_candidates
from app.core.types import ProviderArtistDTO, ProviderTrackDTO


def _candidate(source_id: str, edition: tuple[str, ...]) -> ProviderTrackDTO:
    return ProviderTrackDTO(
        title="Golden",
        artists=(ProviderArtistDTO(name="Myrtle", source="test"),),
        source="test",
        source_id=source_id,
        edition_tags=edition,
    )


def test_edition_awareness_changes_ranking() -> None:
    query = "Myrtle - Golden (Deluxe Edition)"
    deluxe = _candidate("b", ("deluxe",))
    plain = _candidate("a", ())

    aware = rank_candidates(
        query,
        [plain, deluxe],
        min_artist_sim=0.4,
        complete_thr=0.85,
        nearly_thr=0.6,
        fuzzy_max=5,
        edition_aware=True,
    )
    unaware = rank_candidates(
        query,
        [plain, deluxe],
        min_artist_sim=0.4,
        complete_thr=0.85,
        nearly_thr=0.6,
        fuzzy_max=5,
        edition_aware=False,
    )

    assert aware[0].track.source_id == "b"
    assert unaware[0].track.source_id == "a"
    assert aware[0].score.total > unaware[0].score.total
    assert unaware[0].score.total == unaware[1].score.total
