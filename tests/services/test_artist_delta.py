from datetime import datetime

from app.services.artist_delta import (
    AlbumRelease,
    ArtistKnownRelease,
    ArtistTrackCandidate,
    build_artist_delta,
    filter_new_releases,
)


def _make_album_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "album-1",
        "name": "Example Album",
        "artists": [{"name": "Artist"}],
        "release_date": "2024-01-01",
        "release_date_precision": "day",
        "total_tracks": 1,
    }
    payload.update(overrides)
    return payload


def _make_track_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "track-1",
        "name": "Example Track",
        "artists": [{"name": "Artist"}],
        "duration_ms": 123_000,
        "track_number": 1,
    }
    payload.update(overrides)
    return payload


def _build_release(**overrides: object) -> AlbumRelease:
    release = AlbumRelease.from_mapping(_make_album_payload(**overrides), source="spotify")
    assert release is not None
    return release


def _build_candidate(release: AlbumRelease, **overrides: object) -> ArtistTrackCandidate:
    payload = _make_track_payload(**overrides)
    candidate = ArtistTrackCandidate.from_mapping(payload, release, source="spotify")
    assert candidate is not None
    return candidate


def test_filter_new_releases_respects_last_checked() -> None:
    release = _build_release()
    newer = filter_new_releases([release], last_checked=datetime(2023, 12, 31))
    assert newer == (release,)
    older = filter_new_releases([release], last_checked=datetime(2024, 2, 1))
    assert older == ()


def test_filter_new_releases_includes_unknown_dates_when_unchecked() -> None:
    release = _build_release(release_date=None)
    newer = filter_new_releases([release], last_checked=None)
    assert newer == (release,)
    skipped = filter_new_releases([release], last_checked=datetime(2024, 1, 2))
    assert skipped == ()


def test_build_artist_delta_detects_new_tracks() -> None:
    release = _build_release()
    candidate = _build_candidate(release)
    delta = build_artist_delta([candidate], set(), last_checked=datetime(2023, 1, 1))
    assert delta.new == (candidate,)
    assert delta.updated == ()
    assert delta.cache_hint is not None
    assert delta.cache_hint.release_count == 1
    assert delta.cache_hint.latest_release_at == release.release_date


def test_build_artist_delta_skips_known_tracks() -> None:
    release = _build_release()
    candidate = _build_candidate(release)
    track_id = candidate.track_id
    assert track_id is not None
    delta = build_artist_delta([candidate], {track_id}, last_checked=datetime(2023, 1, 1))
    assert delta.new == ()
    assert delta.updated == ()


def test_build_artist_delta_detects_updated_tracks() -> None:
    release = _build_release()
    candidate = _build_candidate(release)
    track_id = candidate.track_id
    assert track_id is not None
    known = {
        track_id: ArtistKnownRelease(track_id=track_id, etag="stale"),
    }
    delta = build_artist_delta([candidate], known, last_checked=datetime(2023, 1, 1))
    assert delta.new == ()
    assert delta.updated == (candidate,)


def test_artist_track_candidate_from_mapping_normalises_variants() -> None:
    release = _build_release()
    payload = {
        "id": 42,
        "name": "Variant Track",
        "artists": [{"name": "Variant"}],
        "duration": "321000",
    }
    candidate = ArtistTrackCandidate.from_mapping(payload, release, source="spotify")
    assert candidate is not None
    assert candidate.track.title == "Variant Track"
    assert candidate.track.duration_ms == 321_000
    assert candidate.cache_key.startswith("artist-track:")


def test_build_artist_delta_cache_hint_captures_latest_release() -> None:
    newer = _build_release(id="album-new", release_date="2024-02-01")
    older = _build_release(id="album-old", release_date="2024-01-01")
    candidates = [_build_candidate(newer), _build_candidate(older, id="track-older")]

    delta = build_artist_delta(candidates, set(), last_checked=datetime(2023, 1, 1))

    assert delta.cache_hint is not None
    assert delta.cache_hint.release_count == 2
    assert delta.cache_hint.latest_release_at == newer.release_date
    assert delta.cache_hint.etag.startswith('"artist-delta:')


def test_album_release_from_mapping_returns_none_without_identifier() -> None:
    release = AlbumRelease.from_mapping({"name": "Invalid"}, source="spotify")
    assert release is None
