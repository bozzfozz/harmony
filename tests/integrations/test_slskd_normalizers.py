"""Tests for slskd normalizer helpers."""
from __future__ import annotations

import pytest

from app.integrations.base import TrackCandidate
from app.integrations.contracts import ProviderArtist, ProviderTrack
from app.integrations.normalizers import (
    from_slskd_album_details,
    from_slskd_artist,
    from_slskd_release,
    normalize_slskd_track,
)


def test_from_slskd_artist_normalizes_payload() -> None:
    payload = {
        "name": "Quasar Ensemble",
        "artist_id": "artist-001",
        "popularity": "87",
        "genres": ["", None],
        "genre": "Electronic",
        "images": [
            {"url": "https://cdn.example.com/quasar.jpg"},
            "https://cdn.example.com/quasar-alt.jpg",
            {"href": "https://cdn.example.com/quasar.jpg"},
        ],
        "aliases": ["QE", ""],
        "metadata": {"origin": "slskd"},
    }

    artist = from_slskd_artist(payload)

    assert artist.source == "slskd"
    assert artist.name == "Quasar Ensemble"
    assert artist.source_id == "artist-001"
    assert artist.popularity == 87
    assert artist.genres == ("Electronic",)
    assert artist.images == (
        "https://cdn.example.com/quasar.jpg",
        "https://cdn.example.com/quasar-alt.jpg",
    )
    assert dict(artist.metadata)["origin"] == "slskd"
    assert dict(artist.metadata)["aliases"] == ["QE"]


def test_from_slskd_artist_requires_name() -> None:
    with pytest.raises(ValueError):
        from_slskd_artist({"name": "  "})


def test_from_slskd_release_handles_alternate_keys() -> None:
    payload = {
        "name": "Hidden Depths",
        "release_id": "rel-01",
        "date": "2021-05-01",
        "release_type": "Album",
        "track_count": "10",
        "edition": "Deluxe",
        "modified_at": "2023-01-01T00:00:00Z",
        "metadata": {"catalog_number": "META-000"},
        "catalogue_number": "ALT-456",
        "catno": "CAT-789",
    }

    release = from_slskd_release(payload, artist_id="artist-01")

    assert release.source == "slskd"
    assert release.source_id == "rel-01"
    assert release.artist_source_id == "artist-01"
    assert release.title == "Hidden Depths"
    assert release.release_date == "2021-05-01"
    assert release.type == "Album"
    assert release.total_tracks == 10
    assert release.version == "Deluxe"
    assert release.updated_at == "2023-01-01T00:00:00Z"

    metadata = dict(release.metadata)
    assert metadata["catalog_number"] == "META-000"
    assert metadata["catalogue_number"] == "ALT-456"
    assert metadata["catno"] == "CAT-789"


def test_from_slskd_album_details_normalizes_tracks_and_metadata() -> None:
    candidate = TrackCandidate(
        title="Existing Track",
        artist="Guest Artist",
        format="MP3",
        bitrate_kbps=192,
        size_bytes=12345,
        seeders=4,
        username="uploader",
        availability=None,
        source="other",
        download_uri=None,
    )
    existing_track = ProviderTrack(
        name="Existing Track",
        provider="other",
        id="track-existing",
        artists=(ProviderArtist(source="other", name="Guest Artist"),),
        album=None,
        duration_ms=None,
        isrc=None,
        score=0.5,
        candidates=(candidate,),
        metadata={"genre": "Pop"},
    )
    payload = {
        "title": "Signal Trails",
        "id": "album-001",
        "date": "2024-03-21",
        "images": [
            {"href": "https://cdn.example.com/albums/signal-trails.jpg"},
            "https://cdn.example.com/albums/signal-trails.jpg",
        ],
        "metadata": {},
        "catalogue_number": "CAT-001",
        "aliases": ["Signal Trails (Deluxe)", ""],
        "genre": "Leftfield",
    }
    tracks = [
        {
            "title": "Opening Transmission",
            "artist": "Quasar Ensemble",
            "album": "Signal Trails",
            "bitrate": 320,
            "size": 2048,
            "score": "0.95",
        },
        existing_track,
    ]

    details = from_slskd_album_details(payload, tracks=tracks)

    assert details.source == "slskd"
    assert details.album.name == "Signal Trails"
    assert details.album.id == "album-001"
    assert details.album.release_date == "2024-03-21"
    assert details.album.total_tracks == 2
    assert details.album.images == (
        "https://cdn.example.com/albums/signal-trails.jpg",
    )
    assert dict(details.album.metadata)["catalogue_number"] == "CAT-001"

    assert len(details.tracks) == 2
    first_track = details.tracks[0]
    assert first_track.name == "Opening Transmission"
    assert [artist.name for artist in first_track.artists] == ["Quasar Ensemble"]
    assert dict(first_track.metadata)["score"] == pytest.approx(0.95)

    second_track = details.tracks[1]
    assert second_track.provider == "slskd"
    assert second_track.name == "Existing Track"
    assert second_track.candidates[0].title == "Existing Track"

    assert dict(details.metadata)["aliases"] == ["Signal Trails (Deluxe)"]
    assert dict(details.metadata)["genre"] == "Leftfield"


def test_from_slskd_album_details_requires_name() -> None:
    with pytest.raises(ValueError):
        from_slskd_album_details({"title": "  "})


def test_normalize_slskd_track_builds_provider_track() -> None:
    payload = {
        "name": "Evening Signal",
        "artists": [
            {"name": "Quasar Ensemble"},
            "Nova Duo",
            "",
        ],
        "format": "flac",
        "bitrate": "320",
        "size": "4096",
        "availability_score": "0.75",
        "path": "/downloads/evening-signal.flac",
        "id": "track-001",
        "genre": "Ambient",
        "genres": ["Ambient", ""],
        "year": "1999",
        "album": "Signal Trails",
        "bitrate_mode": "VBR",
        "metadata": {"track_count": "12"},
        "total_tracks": "8",
    }

    track = normalize_slskd_track(payload)

    assert track.name == "Evening Signal"
    assert track.provider == "slskd"
    assert track.id == "track-001"
    assert [artist.name for artist in track.artists] == [
        "Quasar Ensemble",
        "Nova Duo",
    ]

    assert track.album is not None
    assert track.album.name == "Signal Trails"
    assert track.album.total_tracks == 8
    assert dict(track.album.metadata)["track_count"] == 12
    assert track.album.release_date == "1999"

    assert track.candidates[0].format == "FLAC"
    assert track.candidates[0].availability == pytest.approx(0.75)
    assert track.candidates[0].download_uri == "/downloads/evening-signal.flac"

    metadata = dict(track.metadata)
    assert metadata["genre"] == "Ambient"
    assert metadata["genres"] == ["Ambient"]
    assert metadata["year"] == 1999
    assert metadata["bitrate_mode"] == "VBR"
    assert metadata["total_tracks"] == 8
    assert metadata["track_count"] == 12
