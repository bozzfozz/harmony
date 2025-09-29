"""Unit tests for the enhanced matching engine."""

from __future__ import annotations

from app.config import MatchingConfig
from app.core.matching_engine import MusicMatchingEngine
from app.services.library_service import LibraryAlbum, LibraryService, LibraryTrack


def _build_config() -> MatchingConfig:
    return MatchingConfig(
        edition_aware=True,
        fuzzy_max_candidates=20,
        min_artist_similarity=0.6,
        complete_threshold=0.9,
        nearly_threshold=0.8,
    )


def test_match_track_like_then_normalized_then_fuzzy() -> None:
    service = LibraryService(
        tracks=[
            LibraryTrack(id=1, title="Dreams", artist="Fleetwood Mac"),
            LibraryTrack(id=2, title="Café del Mar", artist="Energy 52"),
            LibraryTrack(id=3, title="Scientist, The", artist="Coldplay"),
        ]
    )
    engine = MusicMatchingEngine(library_service=service, config=_build_config())

    candidate, score = engine.match_track("Dreams", "Fleetwood Mac")
    assert candidate is not None
    assert candidate.id == 1
    assert score > 0.9
    assert engine.last_track_path == "like"

    candidate, score = engine.match_track("Cafe del Mar", "Energy 52")
    assert candidate is not None
    assert candidate.id == 2
    assert score > 0.7
    assert engine.last_track_path == "normalized"

    candidate, score = engine.match_track("The Scientist", "Coldplay")
    assert candidate is not None
    assert candidate.id == 3
    assert score > 0.5
    assert engine.last_track_path == "fuzzy"


def test_match_album_edition_bonus_and_penalty() -> None:
    deluxe = LibraryAlbum(
        id=10,
        title="Evermore (Deluxe Edition)",
        artist="Taylor Swift",
        track_count=19,
    )
    standard = LibraryAlbum(
        id=11,
        title="Evermore",
        artist="Taylor Swift",
        track_count=15,
    )
    live = LibraryAlbum(
        id=12,
        title="Evermore (Live)",
        artist="Taylor Swift",
        track_count=18,
    )
    service = LibraryService(albums=[deluxe, standard, live])
    engine = MusicMatchingEngine(library_service=service, config=_build_config())

    candidate, score = engine.match_album(
        "Evermore (Deluxe Edition)", "Taylor Swift", expected_tracks=19
    )
    assert candidate is not None
    assert candidate.id == 10
    assert score > 0.8
    assert engine.last_album_path == "like"

    deluxe_score = engine._score_album("Evermore (Deluxe Edition)", "Taylor Swift", deluxe, 19)
    standard_score = engine._score_album("Evermore (Deluxe Edition)", "Taylor Swift", standard, 19)
    live_score = engine._score_album("Evermore (Deluxe Edition)", "Taylor Swift", live, 19)

    assert deluxe_score > standard_score
    assert standard_score > live_score


def test_album_completion_thresholds() -> None:
    complete_album = LibraryAlbum(
        id=30,
        title="Complete",
        artist="Artist",
        track_count=20,
        owned_tracks=19,
    )
    nearly_album = LibraryAlbum(
        id=31,
        title="Nearly",
        artist="Artist",
        track_count=20,
        owned_tracks=17,
    )
    incomplete_album = LibraryAlbum(
        id=32,
        title="Incomplete",
        artist="Artist",
        track_count=20,
        owned_tracks=10,
    )
    service = LibraryService(albums=[complete_album, nearly_album, incomplete_album])
    engine = MusicMatchingEngine(library_service=service, config=_build_config())

    owned, expected, is_complete = engine.album_completion(30)
    assert (owned, expected, is_complete) == (19, 20, True)
    assert engine.last_completion_label == "complete"

    owned, expected, is_complete = engine.album_completion(31)
    assert (owned, expected, is_complete) == (17, 20, False)
    assert engine.last_completion_label == "nearly"

    owned, expected, is_complete = engine.album_completion(32)
    assert (owned, expected, is_complete) == (10, 20, False)
    assert engine.last_completion_label == "incomplete"

    owned, expected, is_complete = engine.album_completion(999)
    assert (owned, expected, is_complete) == (0, 0, False)
    assert engine.last_completion_label == "missing"
