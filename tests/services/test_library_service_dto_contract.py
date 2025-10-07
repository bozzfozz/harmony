from __future__ import annotations

import pytest

from app.schemas.provider import ProviderAlbum, ProviderTrack
from app.services.errors import ServiceError
from app.services.library_service import LibraryService


def _track_payload(title: str, artist: str, *, track_id: int) -> dict[str, object]:
    return {
        "id": f"track-{track_id}",
        "name": title,
        "provider": "spotify",
        "artists": [{"name": artist}],
        "metadata": {"bitrate_kbps": 320},
    }


def _album_payload(title: str, artist: str, *, album_id: int) -> dict[str, object]:
    return {
        "id": f"album-{album_id}",
        "name": title,
        "artists": [{"name": artist}],
        "metadata": {"genres": ["rock"]},
    }


def test_library_service_accepts_provider_dtos() -> None:
    service = LibraryService()
    service.add_tracks(
        [
            _track_payload("Song A", "Artist One", track_id=1),
            _track_payload("Song B", "Artist Two", track_id=2),
        ]
    )
    service.add_albums(
        [
            _album_payload("Album A", "Artist One", album_id=10),
            _album_payload("Album B", "Artist Two", album_id=11),
        ]
    )

    like_matches = service.search_tracks_like(["Song"], ["Artist"], limit=5)
    assert all(isinstance(item, ProviderTrack) for item in like_matches)
    assert {track.name for track in like_matches} == {"Song A", "Song B"}

    fuzzy_matches = service.search_tracks_fuzzy("Song A", "Artist One", limit=5)
    assert fuzzy_matches and fuzzy_matches[0].name == "Song A"

    album_matches = service.search_albums_like(["Album"], ["Artist"], limit=5)
    assert all(isinstance(item, ProviderAlbum) for item in album_matches)
    assert {album.name for album in album_matches} == {"Album A", "Album B"}


def test_library_service_limit_validation() -> None:
    service = LibraryService()
    service.add_tracks([_track_payload("Song", "Artist", track_id=1)])

    with pytest.raises(ServiceError):
        service.search_tracks_like(["Song"], ["Artist"], limit=0)


def test_library_service_normalized_lookup() -> None:
    service = LibraryService()
    service.add_tracks([_track_payload("Sóng Á", "Ártist", track_id=1)])

    matches = service.search_tracks_like_normalized(["Song A"], ["Artist"], limit=5)
    assert matches and matches[0].name == "Sóng Á"


def test_library_service_content_hash_is_deterministic() -> None:
    payloads = [
        _track_payload("Song A", "Artist One", track_id=1),
        _track_payload("Song B", "Artist Two", track_id=2),
    ]
    albums = [
        _album_payload("Album A", "Artist One", album_id=10),
        _album_payload("Album B", "Artist Two", album_id=11),
    ]

    service = LibraryService()
    service.add_tracks(payloads)
    service.add_albums(albums)
    first_hash = service.compute_content_hash()

    reordered = LibraryService()
    reordered.add_tracks(list(reversed(payloads)))
    reordered.add_albums(list(reversed(albums)))

    assert reordered.compute_content_hash() == first_hash


def test_library_service_content_hash_changes_on_mutation() -> None:
    base = LibraryService()
    base.add_tracks([_track_payload("Song", "Artist", track_id=1)])
    base.add_albums([_album_payload("Album", "Artist", album_id=1)])
    base_hash = base.compute_content_hash()

    mutated = LibraryService()
    mutated.add_tracks([_track_payload("Song", "Artist", track_id=1)])
    mutated.add_albums([_album_payload("Album", "Artist", album_id=1)])
    mutated.add_tracks([_track_payload("Song Two", "Artist", track_id=2)])

    assert mutated.compute_content_hash() != base_hash
