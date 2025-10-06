"""Music provider adapters for Harmony integrations."""

from .artist_gateway import (
    ArtistDTO,
    ArtistGateway,
    ArtistGatewayResponse,
    ArtistGatewayResult,
    ArtistReleaseDTO,
)
from .base import Album, Artist, MusicProvider, Playlist, Track

__all__ = [
    "Album",
    "Artist",
    "ArtistDTO",
    "ArtistGateway",
    "ArtistGatewayResponse",
    "ArtistGatewayResult",
    "ArtistReleaseDTO",
    "MusicProvider",
    "Playlist",
    "Track",
]
