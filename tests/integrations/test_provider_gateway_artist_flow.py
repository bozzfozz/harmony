from __future__ import annotations

import pytest

from app.integrations.contracts import (
    ProviderAlbum,
    ProviderAlbumDetails,
    ProviderArtist,
    ProviderRelease,
    ProviderTrack,
    SearchQuery,
)
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewayConfig,
    ProviderRetryPolicy,
)


class DummyProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.artist_calls: list[tuple[str | None, str | None]] = []
        self.release_calls: list[tuple[str, int | None]] = []
        self.album_calls: list[str] = []
        self.top_calls: list[tuple[str, int | None]] = []

    async def search_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        return []

    async def fetch_artist(
        self, *, artist_id: str | None = None, name: str | None = None
    ) -> ProviderArtist:
        self.artist_calls.append((artist_id, name))
        identifier = artist_id or name or "unknown"
        return ProviderArtist(
            source=self.name,
            source_id=identifier,
            name=f"{self.name.title()} Artist",
        )

    async def fetch_artist_releases(
        self, artist_source_id: str, *, limit: int | None = None
    ) -> list[ProviderRelease]:
        self.release_calls.append((artist_source_id, limit))
        return [
            ProviderRelease(
                source=self.name,
                source_id=f"{artist_source_id}-{self.name}-1",
                artist_source_id=artist_source_id,
                title=f"{self.name.title()} Release",
                type="album",
            )
        ]

    async def fetch_album(self, album_source_id: str) -> ProviderAlbumDetails:
        self.album_calls.append(album_source_id)
        album = ProviderAlbum(name=f"{self.name.title()} Album", id=album_source_id)
        return ProviderAlbumDetails(
            source=self.name,
            album=album,
            tracks=(
                ProviderTrack(name="Top Song", provider=self.name),
            ),
        )

    async def fetch_artist_top_tracks(
        self, artist_source_id: str, *, limit: int | None = None
    ) -> list[ProviderTrack]:
        self.top_calls.append((artist_source_id, limit))
        return [ProviderTrack(name=f"{self.name.title()} Hit", provider=self.name)]


@pytest.mark.asyncio
async def test_gateway_returns_uniform_dtos_for_all_providers() -> None:
    config = ProviderGatewayConfig(
        max_concurrency=2,
        default_policy=ProviderRetryPolicy(
            timeout_ms=1000,
            retry_max=0,
            backoff_base_ms=50,
            jitter_pct=0.0,
        ),
        provider_policies={},
    )
    spotify = DummyProvider("spotify")
    slskd = DummyProvider("slskd")
    gateway = ProviderGateway(providers={"spotify": spotify, "slskd": slskd}, config=config)

    spotify_artist = await gateway.fetch_artist("spotify", artist_id="artist-1")
    spotify_releases = await gateway.fetch_artist_releases("spotify", "artist-1", limit=5)
    spotify_album = await gateway.fetch_album("spotify", "album-1")
    spotify_top_tracks = await gateway.fetch_artist_top_tracks("spotify", "artist-1", limit=3)
    slskd_artist = await gateway.fetch_artist("slskd", artist_id="artist-1")
    slskd_releases = await gateway.fetch_artist_releases("slskd", "artist-1")
    slskd_album = await gateway.fetch_album("slskd", "album-2")
    slskd_top_tracks = await gateway.fetch_artist_top_tracks("slskd", "artist-1")

    assert spotify_artist.source == "spotify"
    assert spotify_artist.name == "Spotify Artist"
    assert spotify_releases[0].source == "spotify"
    assert spotify_album.source == "spotify"
    assert spotify_album.album.name == "Spotify Album"
    assert spotify_top_tracks[0].provider == "spotify"
    assert slskd_artist.source == "slskd"
    assert slskd_releases[0].source == "slskd"
    assert slskd_album.source == "slskd"
    assert slskd_album.album.name == "Slskd Album"
    assert slskd_top_tracks[0].provider == "slskd"

    assert spotify.artist_calls == [("artist-1", None)]
    assert slskd.artist_calls == [("artist-1", None)]
    assert spotify.release_calls == [("artist-1", 5)]
    assert slskd.release_calls == [("artist-1", None)]
    assert spotify.album_calls == ["album-1"]
    assert slskd.album_calls == ["album-2"]
    assert spotify.top_calls == [("artist-1", 3)]
    assert slskd.top_calls == [("artist-1", None)]
