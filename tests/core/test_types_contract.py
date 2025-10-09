from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.errors import InvalidInputError
from app.core.types import (
    MatchScore,
    ProviderArtistDTO,
    ProviderTrackDTO,
    ensure_track_dto,
    extract_edition_tags,
)


def test_provider_artist_alias_deduplication() -> None:
    artist = ProviderArtistDTO(name="Aurora", source="spotify", aliases=("Rora", "rora", "Aura"))
    assert artist.aliases == ("Rora", "Aura")


def test_ensure_track_dto_from_mapping() -> None:
    payload = {
        "title": "Runaway",
        "source": "spotify",
        "id": "track-1",
        "artists": [{"name": "Aurora", "aliases": ["Rora"]}],
        "album": {
            "title": "Runaway (Deluxe Edition)",
            "year": 2015,
            "edition_tags": ["deluxe"],
        },
        "metadata": {"bitrate_kbps": 320},
    }
    dto = ensure_track_dto(payload)
    assert dto.source == "spotify"
    assert dto.source_id == "track-1"
    assert dto.primary_artist == "Aurora"
    assert dto.album is not None and dto.album.year == 2015
    assert "deluxe" in dto.combined_edition_tags
    assert dto.metadata["bitrate_kbps"] == 320


def test_ensure_track_dto_from_object() -> None:
    candidate = SimpleNamespace(
        title="Song",
        artist="Singer",
        source="slskd",
        username="uploader",
        metadata={"bitrate_kbps": 192},
    )
    dto = ensure_track_dto(candidate)
    assert dto.source == "slskd"
    assert dto.primary_artist == "Singer"
    assert dto.metadata.get("username") == "uploader"


def test_match_score_total_computation() -> None:
    score = MatchScore(title=0.9, artist=0.8, album=0.5, bonus=0.05, penalty=0.1)
    assert 0.75 < score.total < 0.9


def test_extract_edition_tags() -> None:
    tags = extract_edition_tags("Live & Deluxe Edition")
    assert set(tags) >= {"deluxe", "live"}


def test_invalid_track_raises() -> None:
    with pytest.raises(InvalidInputError):
        ProviderTrackDTO(title="", artists=(), source="test")
