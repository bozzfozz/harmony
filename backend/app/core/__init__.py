"""Core service integrations for the backend package."""

from backend.app.core.matching_engine import (
    MusicMatchingEngine,
    PlexTrackInfo,
    SoulseekTrackResult,
    SpotifyTrack,
)
from backend.app.core.plex_client import PlexClient
from backend.app.core.spotify_client import SpotifyClient


__all__ = [
    "PlexClient",
    "SpotifyClient",
    "MusicMatchingEngine",
    "SpotifyTrack",
    "PlexTrackInfo",
    "SoulseekTrackResult",
]

