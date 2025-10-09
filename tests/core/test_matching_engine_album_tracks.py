from app.core.matching_engine import calculate_slskd_match_confidence
from app.core.types import ensure_track_dto


def test_ensure_album_dto_falls_back_to_metadata_track_counts() -> None:
    spotify_track = {
        "name": "Aligned Song",
        "artists": [{"name": "Sample Artist"}],
        "album": {
            "name": "Aligned Album",
            "metadata": {"track_count": 11},
        },
    }

    dto = ensure_track_dto(spotify_track, default_source="spotify")

    assert dto.album is not None
    assert dto.album.total_tracks == 11


def test_match_confidence_rewards_album_track_alignment() -> None:
    spotify_track = {
        "name": "Aligned Song",
        "artists": [{"name": "Sample Artist"}],
        "album": {
            "name": "Aligned Album",
            "metadata": {"track_count": 10},
        },
    }
    base_candidate = {
        "name": "Aligned Song",
        "artist": "Sample Artist",
        "metadata": {"bitrate": 128},
    }

    aligned_entry = {
        **base_candidate,
        "album": {"name": "Aligned Album", "total_tracks": 10},
    }
    off_by_one_entry = {
        **base_candidate,
        "album": {"name": "Aligned Album", "total_tracks": 9},
    }
    diverging_entry = {
        **base_candidate,
        "album": {"name": "Aligned Album", "total_tracks": 3},
    }

    aligned_confidence = calculate_slskd_match_confidence(spotify_track, aligned_entry)
    off_by_one_confidence = calculate_slskd_match_confidence(
        spotify_track, off_by_one_entry
    )
    diverging_confidence = calculate_slskd_match_confidence(
        spotify_track, diverging_entry
    )

    assert aligned_confidence >= off_by_one_confidence
    assert aligned_confidence - diverging_confidence >= 0.1
    assert off_by_one_confidence - diverging_confidence >= 0.05
    assert diverging_confidence < 1.0
