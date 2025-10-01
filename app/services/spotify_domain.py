"""Backward compatibility module for the consolidated Spotify domain service."""

from __future__ import annotations

from warnings import warn

from .spotify_domain_service import PlaylistItemsResult, SpotifyDomainService

warn(
    "app.services.spotify_domain is deprecated; import from app.services.spotify_domain_service instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["SpotifyDomainService", "PlaylistItemsResult"]
