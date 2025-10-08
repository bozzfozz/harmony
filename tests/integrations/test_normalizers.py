from app.integrations.normalizers import (from_slskd_album_details,
                                          from_slskd_artist,
                                          from_slskd_release,
                                          from_spotify_album_details,
                                          from_spotify_artist,
                                          from_spotify_release,
                                          normalize_slskd_track,
                                          normalize_spotify_track)


def test_normalize_spotify_track_handles_missing_fields() -> None:
    track = normalize_spotify_track({"name": "Example"})

    assert track.name == "Example"
    assert track.provider == "spotify"
    assert track.id is None
    assert track.artists == ()
    assert track.metadata.get("id") is None
    assert track.score is None


def test_normalize_slskd_track_handles_partial_payload() -> None:
    track = normalize_slskd_track({"title": "Loose"})

    assert track.name == "Loose"
    assert track.provider == "slskd"
    assert track.id is None
    assert track.score is None
    assert track.candidates, "Expected candidate entry"
    candidate = track.candidates[0]
    assert candidate.title == "Loose"
    assert candidate.source == "slskd"


def test_normalize_spotify_artist_and_releases() -> None:
    artist_payload = {
        "id": "artist-1",
        "name": "Test Artist",
        "popularity": 83,
        "genres": ["alt-rock", "indie"],
        "images": [{"url": "https://example.com/image.jpg"}],
        "followers": {"total": 12345},
    }
    artist = from_spotify_artist(artist_payload)

    assert artist.source == "spotify"
    assert artist.source_id == "artist-1"
    assert artist.name == "Test Artist"
    assert artist.popularity == 83
    assert artist.genres == ("alt-rock", "indie")
    assert artist.images == ("https://example.com/image.jpg",)
    assert artist.metadata["followers"] == 12345

    release_payload = {
        "id": "release-1",
        "name": "Album",
        "release_date": "2024-01-01",
        "album_type": "album",
        "total_tracks": 11,
        "release_date_precision": "day",
        "available_markets": ["US", "DE"],
    }
    release = from_spotify_release(release_payload, "artist-1")

    assert release.source == "spotify"
    assert release.source_id == "release-1"
    assert release.artist_source_id == "artist-1"
    assert release.title == "Album"
    assert release.type == "album"
    assert release.total_tracks == 11
    assert release.release_date == "2024-01-01"
    assert release.metadata["available_markets"] == ["US", "DE"]


def test_from_spotify_album_details_includes_tracks() -> None:
    album_payload = {
        "id": "album-1",
        "name": "Example Album",
        "release_date": "2024-01-01",
        "total_tracks": 2,
        "images": ["https://example.com/cover.jpg"],
        "artists": [{"id": "artist-1", "name": "Artist"}],
        "label": "Indie",
        "available_markets": ["US", "DE"],
    }
    track_payloads = [
        {
            "id": "track-1",
            "name": "Track One",
            "duration_ms": 180000,
            "artists": [{"id": "artist-1", "name": "Artist"}],
        }
    ]

    details = from_spotify_album_details(album_payload, tracks=track_payloads)

    assert details.source == "spotify"
    assert details.album.name == "Example Album"
    assert details.album.release_date == "2024-01-01"
    assert details.album.total_tracks == 2
    assert details.album.images == ("https://example.com/cover.jpg",)
    assert len(details.tracks) == 1
    assert details.tracks[0].album is not None
    assert details.tracks[0].album.name == "Example Album"


def test_normalize_slskd_artist_and_releases() -> None:
    artist_payload = {
        "id": "artist-1",
        "name": "Soulseek Artist",
        "genres": ["metal"],
        "aliases": ["Alias"],
        "metadata": {"origin": "community"},
    }
    artist = from_slskd_artist(artist_payload)

    assert artist.source == "slskd"
    assert artist.source_id == "artist-1"
    assert artist.name == "Soulseek Artist"
    assert artist.genres == ("metal",)
    assert artist.metadata["origin"] == "community"
    assert artist.metadata["aliases"] == ["Alias"]

    release_payload = {
        "id": "release-1",
        "title": "Live Bootleg",
        "total_tracks": 8,
        "metadata": {"format": "FLAC"},
    }
    release = from_slskd_release(release_payload, "artist-1")

    assert release.source == "slskd"
    assert release.source_id == "release-1"
    assert release.artist_source_id == "artist-1"
    assert release.title == "Live Bootleg"
    assert release.total_tracks == 8
    assert release.metadata["format"] == "FLAC"


def test_from_slskd_album_details_derives_metadata_from_tracks() -> None:
    track = normalize_slskd_track(
        {
            "title": "Song A",
            "artist": "Soulseek Artist",
            "album": "Live Bootleg",
            "year": 1999,
            "genre": "metal",
        }
    )

    details = from_slskd_album_details({"id": "rel-1", "title": "Live Bootleg"}, tracks=[track])

    assert details.source == "slskd"
    assert details.album.name == "Live Bootleg"
    assert details.album.total_tracks == 1
    assert details.tracks[0].name == "Song A"
