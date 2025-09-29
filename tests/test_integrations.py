from __future__ import annotations

from app.config import _parse_enabled_providers, _parse_provider_timeouts
from app.integrations.base import Album, Artist, MusicProvider, Playlist
from app.services.integration_service import IntegrationService


def test_parse_enabled_providers_deduplicates_and_normalises() -> None:
    result = _parse_enabled_providers("Spotify, Plex, spotify \n slskd")
    assert result == ("spotify", "plex", "slskd")


def test_parse_provider_timeouts_reads_env_values() -> None:
    result = _parse_provider_timeouts(
        {
            "SPOTIFY_TIMEOUT_MS": "2000",
            "PLEX_TIMEOUT_MS": "3000",
            "SLSKD_TIMEOUT_MS": "not-a-number",
        }
    )
    assert result["spotify"] == 2000
    assert result["plex"] == 3000
    assert result["slskd"] == 8000


class _StubProvider(MusicProvider):
    name = "stub"

    def search_tracks(self, query: str, limit: int = 20):  # pragma: no cover - unused legacy API
        return []

    def get_artist(self, artist_id: str) -> Artist:  # pragma: no cover - legacy API
        raise NotImplementedError

    def get_album(self, album_id: str) -> Album:  # pragma: no cover - legacy API
        raise NotImplementedError

    def get_artist_top_tracks(self, artist_id: str, limit: int = 10):  # pragma: no cover
        raise NotImplementedError

    def get_playlist(self, playlist_id: str) -> Playlist:  # pragma: no cover
        raise NotImplementedError


class _StubRegistry:
    def __init__(self, providers: dict[str, MusicProvider]) -> None:
        self._providers = providers
        self.enabled_names = tuple(providers.keys())

    def initialise(self) -> None:  # pragma: no cover - trivial setup
        return None

    def get(self, name: str) -> MusicProvider:
        return self._providers[name]

    def all(self):  # pragma: no cover - unused helper
        return self._providers.values()


def test_integration_service_health_marks_enabled() -> None:
    registry = _StubRegistry({"stub": _StubProvider()})
    service = IntegrationService(registry=registry)  # type: ignore[arg-type]

    health = service.health()

    assert health[0].name == "stub"
    assert health[0].enabled is True
    assert health[0].health == "ok"
