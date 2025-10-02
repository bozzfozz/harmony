"""Harmony core domain exports."""

from .errors import InvalidInputError
from .matching_engine import (
    MusicMatchingEngine,
    calculate_slskd_match_confidence,
    compute_relevance_score,
    rank_candidates,
)
from .types import (
    MatchResult,
    MatchScore,
    ProviderAlbumDTO,
    ProviderArtistDTO,
    ProviderTrackDTO,
    ensure_album_dto,
    ensure_artist_dto,
    ensure_track_dto,
)

__all__ = [
    "InvalidInputError",
    "MatchResult",
    "MatchScore",
    "MusicMatchingEngine",
    "ProviderAlbumDTO",
    "ProviderArtistDTO",
    "ProviderTrackDTO",
    "calculate_slskd_match_confidence",
    "compute_relevance_score",
    "ensure_album_dto",
    "ensure_artist_dto",
    "ensure_track_dto",
    "rank_candidates",
]
