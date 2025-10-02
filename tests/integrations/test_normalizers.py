from app.integrations.normalizers import normalize_slskd_track, normalize_spotify_track


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
