"""Unit tests for the backend Spotify client wrapper."""

from __future__ import annotations

import pytest

from backend.app.core.spotify_client import SpotifyClient


class FakeAuthManager:
    def __init__(self) -> None:
        self._token = {"access_token": "token"}

    def get_cached_token(self) -> dict[str, str]:
        return dict(self._token)


class FakeSpotifyAPI:
    def __init__(self) -> None:
        self._track_calls: list[str] = []

    def search(self, *, q: str, type: str, limit: int) -> dict:
        if type == "track":
            return {
                "tracks": {
                    "items": [
                        {
                            "id": "track-1",
                            "name": "Song One",
                            "artists": [{"name": "Artist A"}],
                            "album": {"name": "Album X"},
                            "duration_ms": 210000,
                            "popularity": 55,
                        }
                    ]
                }
            }
        if type == "artist":
            return {
                "artists": {
                    "items": [
                        {
                            "id": "artist-1",
                            "name": "Artist A",
                            "genres": ["rock"],
                            "followers": {"total": 1000},
                        }
                    ]
                }
            }
        if type == "album":
            return {
                "albums": {
                    "items": [
                        {
                            "id": "album-1",
                            "name": "Album X",
                            "artists": [{"name": "Artist A"}],
                            "release_date": "2020-01-01",
                            "total_tracks": 10,
                        }
                    ]
                }
            }
        raise ValueError(f"Unsupported search type {type}")

    def current_user_playlists(self) -> dict:
        return {
            "items": [
                {
                    "id": "playlist-1",
                    "name": "Favourites",
                    "owner": {"display_name": "Tester"},
                    "tracks": {"total": 25},
                }
            ]
        }

    def track(self, track_id: str) -> dict:
        self._track_calls.append(track_id)
        return {
            "id": track_id,
            "name": "Song One",
            "artists": [{"name": "Artist A"}],
            "album": {"id": "album-1", "name": "Album X", "release_date": "2020-01-01"},
            "duration_ms": 210000,
            "popularity": 55,
            "preview_url": "https://example.com/sample.mp3",
            "uri": "spotify:track:track-1",
        }


@pytest.fixture()
def spotify_client() -> SpotifyClient:
    return SpotifyClient(client=FakeSpotifyAPI(), auth_manager=FakeAuthManager(), rate_limit_seconds=0, max_retries=1)


def test_is_authenticated_uses_cached_token(spotify_client: SpotifyClient) -> None:
    assert spotify_client.is_authenticated() is True


def test_search_tracks_returns_formatted_results(spotify_client: SpotifyClient) -> None:
    results = spotify_client.search_tracks("Song")
    assert results == [
        {
            "id": "track-1",
            "name": "Song One",
            "artists": ["Artist A"],
            "album": "Album X",
            "duration_ms": 210000,
            "popularity": 55,
        }
    ]


def test_search_artists_returns_expected_payload(spotify_client: SpotifyClient) -> None:
    results = spotify_client.search_artists("Artist")
    assert results == [
        {
            "id": "artist-1",
            "name": "Artist A",
            "genres": ["rock"],
            "followers": 1000,
        }
    ]


def test_search_albums_returns_expected_payload(spotify_client: SpotifyClient) -> None:
    results = spotify_client.search_albums("Album")
    assert results == [
        {
            "id": "album-1",
            "name": "Album X",
            "artists": ["Artist A"],
            "release_date": "2020-01-01",
            "total_tracks": 10,
        }
    ]


def test_get_user_playlists_formats_response(spotify_client: SpotifyClient) -> None:
    playlists = spotify_client.get_user_playlists()
    assert playlists == [
        {
            "id": "playlist-1",
            "name": "Favourites",
            "owner": "Tester",
            "tracks": 25,
        }
    ]


def test_get_track_details_returns_structured_payload(spotify_client: SpotifyClient) -> None:
    details = spotify_client.get_track_details("track-1")
    assert details["id"] == "track-1"
    assert details["album"]["name"] == "Album X"
    assert details["artists"] == ["Artist A"]
