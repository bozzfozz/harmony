"""Helpers for setting up artist workflow data in tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.integrations.contracts import ProviderArtist, ProviderRelease
from app.models import WatchlistArtist
from tests.fixtures.mocks_providers import ArtistGatewayMock


@dataclass(slots=True)
class ArtistTestState:
    """Track mutable state for a configured test artist."""

    artist_key: str
    spotify_id: str
    watchlist_id: int
    album_id: str
    release_title: str
    track_id: str
    gateway: ArtistGatewayMock
    provider_artist: ProviderArtist
    releases: list[ProviderRelease]

    def update_gateway(
        self,
        *,
        provider: str,
        artist: ProviderArtist,
        releases: Sequence[ProviderRelease],
    ) -> None:
        """Replace the configured gateway response for this artist."""

        self.releases = list(releases)
        self.gateway.set_response(
            self.spotify_id,
            provider=provider,
            artist=artist,
            releases=releases,
        )


class ArtistFactory:
    """Factory producing artist workflow fixtures with consistent stubs."""

    def __init__(
        self,
        *,
        spotify_stub,
        soulseek_stub,
        gateway_stub: ArtistGatewayMock,
    ) -> None:
        self._spotify = spotify_stub
        self._soulseek = soulseek_stub
        self._gateway = gateway_stub

    def create(
        self,
        artist_key: str = "spotify:artist-1",
        *,
        name: str = "Test Artist",
        priority: int = 5,
        album_id: str = "album-harmony",
        release_title: str = "Harmony Release",
        release_date: str = "2024-03-01",
        release_type: str = "album",
        track_id: str = "track-harmony",
        track_name: str = "Harmony Song",
        track_duration_ms: int = 215_000,
    ) -> ArtistTestState:
        """Insert a watchlist artist and configure provider stubs."""

        source, _, identifier = artist_key.partition(":")
        spotify_id = identifier or artist_key

        with session_scope() as session:
            existing = session.execute(
                select(WatchlistArtist).where(WatchlistArtist.spotify_artist_id == spotify_id)
            ).scalars().first()
            if existing is not None:
                session.delete(existing)
                session.flush()
            record = WatchlistArtist(
                spotify_artist_id=spotify_id,
                name=name,
                priority=priority,
                cooldown_s=0,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(record)
            session.flush()
            watchlist_id = int(record.id)

        self._spotify.artist_albums[spotify_id] = [
            {
                "id": album_id,
                "name": release_title,
                "artists": [{"name": name}],
                "release_date": release_date,
                "release_date_precision": "day",
            }
        ]
        self._spotify.album_tracks[album_id] = [
            {
                "id": track_id,
                "name": track_name,
                "artists": [{"name": name}],
                "duration_ms": track_duration_ms,
                "track_number": 1,
                "disc_number": 1,
                "explicit": False,
                "external_ids": {"isrc": "ISRC00000001"},
            }
        ]

        self._soulseek.search_results = [
            {
                "username": "collector",
                "files": [
                    {
                        "id": f"slsk-{track_id}",
                        "filename": f"{track_name}.flac",
                        "title": track_name,
                        "artist": name,
                        "album": release_title,
                        "bitrate": 1000,
                        "format": "flac",
                        "year": int(release_date[:4]),
                        "genre": "rock",
                    }
                ],
            }
        ]

        provider_artist = ProviderArtist(source=source or "spotify", name=name, source_id=spotify_id)
        provider_release = ProviderRelease(
            source=source or "spotify",
            source_id=album_id,
            artist_source_id=spotify_id,
            title=release_title,
            release_date=release_date,
            type=release_type,
            total_tracks=1,
        )
        self._gateway.set_response(
            spotify_id,
            provider=provider_artist.source,
            artist=provider_artist,
            releases=(provider_release,),
        )

        return ArtistTestState(
            artist_key=artist_key,
            spotify_id=spotify_id,
            watchlist_id=watchlist_id,
            album_id=album_id,
            release_title=release_title,
            track_id=track_id,
            gateway=self._gateway,
            provider_artist=provider_artist,
            releases=[provider_release],
        )


@pytest.fixture
def artist_factory(client, artist_gateway_stub) -> ArtistFactory:
    """Yield an artist factory bound to the active client stubs."""

    return ArtistFactory(
        spotify_stub=client.app.state.spotify_stub,
        soulseek_stub=client.app.state.soulseek_stub,
        gateway_stub=artist_gateway_stub,
    )

