"""Tests covering the matching engine and API endpoints."""

from __future__ import annotations

import pytest

from app.db import SessionLocal, init_db
from backend.app.core.matching_engine import (
    MusicMatchingEngine,
    PlexTrackInfo,
    SoulseekTrackResult,
    SpotifyTrack,
)
from backend.app.models.matching_models import MatchHistory
from backend.app.models.plex_models import PlexAlbum, PlexArtist, PlexTrack
from backend.app.routers import matching_router
from fastapi import HTTPException


class SimpleResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class SimpleTestClient:
    """Minimal stand-in for FastAPI's TestClient used in tests."""

    def post(self, path: str, json: dict[str, object]) -> SimpleResponse:
        if path == "/matching/spotify-to-plex":
            request = matching_router.SpotifyToPlexRequest(**json)
            with SessionLocal() as session:
                try:
                    result = matching_router.match_spotify_to_plex(request, db=session)
                except HTTPException as exc:  # pragma: no cover - defensive safety net
                    return SimpleResponse(exc.status_code, {"detail": exc.detail or ""})
            if hasattr(result, "model_dump"):
                payload = result.model_dump()
            elif hasattr(result, "dict"):
                payload = result.dict()
            else:
                payload = result
            return SimpleResponse(200, payload)

        if path == "/matching/spotify-to-soulseek":
            request = matching_router.SpotifyToSoulseekRequest(**json)
            with SessionLocal() as session:
                try:
                    result = matching_router.match_spotify_to_soulseek(request, db=session)
                except HTTPException as exc:  # pragma: no cover - defensive safety net
                    return SimpleResponse(exc.status_code, {"detail": exc.detail or ""})
            if hasattr(result, "model_dump"):
                payload = result.model_dump()
            elif hasattr(result, "dict"):
                payload = result.dict()
            else:
                payload = result
            return SimpleResponse(200, payload)

        raise AssertionError(f"Unsupported path {path}")


@pytest.fixture(autouse=True)
def prepare_database() -> None:
    init_db()
    with SessionLocal() as session:
        session.query(MatchHistory).delete()
        session.query(PlexTrack).delete()
        session.query(PlexAlbum).delete()
        session.query(PlexArtist).delete()
        session.commit()
    yield
    with SessionLocal() as session:
        session.query(MatchHistory).delete()
        session.query(PlexTrack).delete()
        session.query(PlexAlbum).delete()
        session.query(PlexArtist).delete()
        session.commit()


def test_calculate_match_confidence_handles_normalisation() -> None:
    engine = MusicMatchingEngine()
    spotify_track = SpotifyTrack(
        id="sp1",
        name="Song Title (feat. Guest) - Remastered 2011",
        artists=["Main Artist"],
        album="Great Album (Special Edition)",
        duration_ms=200_000,
    )
    plex_track = PlexTrackInfo(
        id="pl1",
        title="Song Title",
        artist="Main Artist",
        album="Great Album",
        duration_ms=199_500,
    )

    confidence = engine.calculate_match_confidence(spotify_track, plex_track)

    assert confidence > 0.85


def test_calculate_slskd_match_confidence_accounts_for_duration() -> None:
    engine = MusicMatchingEngine()
    spotify_track = SpotifyTrack(
        id="sp1",
        name="Song Title",
        artists=["Main Artist"],
        album="Great Album",
        duration_ms=210_000,
    )
    slskd_result = SoulseekTrackResult(
        id="result-1",
        title="Main Artist - Song Title (Remastered)",
        artist="Main Artist",
        filename="Main Artist - Song Title.mp3",
        duration_ms=211_000,
        bitrate=320,
    )

    confidence = engine.calculate_slskd_match_confidence(spotify_track, slskd_result)

    assert confidence > 0.7


class FakeSpotifyClient:
    def get_track_details(self, track_id: str) -> dict:
        return {
            "id": track_id,
            "name": "Song Title (feat. Guest)",
            "artists": ["Main Artist"],
            "album": {"name": "Great Album"},
            "duration_ms": 200_000,
        }


@pytest.fixture()
def test_app(monkeypatch: pytest.MonkeyPatch) -> SimpleTestClient:
    monkeypatch.setattr(matching_router, "spotify_client", FakeSpotifyClient())
    monkeypatch.setattr(matching_router, "matching_engine", MusicMatchingEngine())
    return SimpleTestClient()


def test_matching_plex_endpoint_returns_best_result(test_app: SimpleTestClient) -> None:
    with SessionLocal() as session:
        session.add(PlexArtist(id="artist-1", name="Main Artist"))
        session.add(PlexAlbum(id="album-1", title="Great Album", artist_id="artist-1"))
        session.add(PlexTrack(id="track-1", title="Song Title", album_id="album-1", duration=200_000))
        session.add(PlexTrack(id="track-2", title="Unrelated", album_id="album-1", duration=180_000))
        session.commit()

    response = test_app.post(
        "/matching/spotify-to-plex",
        json={"spotify_track_id": "sp1", "plex_artist_id": "artist-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["matched"] is True
    assert payload["target_id"] == "track-1"

    with SessionLocal() as session:
        history = session.query(MatchHistory).all()

    assert len(history) == 1
    assert history[0].source == "plex"


def test_matching_soulseek_endpoint_returns_best_result(test_app: SimpleTestClient) -> None:
    response = test_app.post(
        "/matching/spotify-to-soulseek",
        json={
            "spotify_track_id": "sp1",
            "results": [
                {
                    "id": "result-1",
                    "title": "Main Artist - Song Title",
                    "artist": "Main Artist",
                    "filename": "Main Artist - Song Title.mp3",
                    "duration_ms": 200_000,
                    "bitrate": 320,
                },
                {
                    "id": "result-2",
                    "title": "Other Track",
                    "artist": "Someone Else",
                    "filename": "Other Track.mp3",
                    "duration_ms": 150_000,
                    "bitrate": 192,
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["matched"] is True
    assert payload["target_id"] == "result-1"

    with SessionLocal() as session:
        history = session.query(MatchHistory).order_by(MatchHistory.id.asc()).all()

    assert len(history) == 1
    assert history[0].source == "soulseek"
