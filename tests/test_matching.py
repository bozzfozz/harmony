import pytest

from app.core.matching_engine import MusicMatchingEngine
from app.integrations.normalizers import normalize_slskd_candidate, normalize_spotify_track
from app.models import Match
from tests.simple_client import SimpleTestClient


@pytest.fixture
def matching_engine() -> MusicMatchingEngine:
    return MusicMatchingEngine()


def test_slskd_confidence_scoring(matching_engine: MusicMatchingEngine) -> None:
    spotify_track = normalize_spotify_track(
        {"name": "Song", "artists": [{"name": "Artist"}], "duration_ms": 200000}
    )
    candidate = normalize_slskd_candidate(
        {"filename": "Artist - Song", "username": "Artist", "bitrate": 320}
    )

    score = matching_engine.calculate_slskd_match_confidence(spotify_track, candidate)

    assert 0.65 < score <= 1.0


def test_matching_api_soulseek(
    client: SimpleTestClient, db_session
) -> None:  # type: ignore[reportGeneralTypeIssues]
    payload = {
        "spotify_track": {"id": "track-1", "name": "Example Song"},
        "candidates": [
            {"id": "candidate-1", "filename": "Other.mp3", "username": "other", "bitrate": 128},
            {"id": "candidate-2", "filename": "Example Song.mp3", "username": "dj", "bitrate": 320},
        ],
    }

    response = client.post("/matching/spotify-to-soulseek", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["best_match"]["id"] == "candidate-2"
    assert data["confidence"] > 0.5

    saved = db_session.query(Match).filter(Match.source == "spotify-to-soulseek").all()
    assert len(saved) == 1
    assert saved[0].target_id == "candidate-2"
