"""Backward compatibility module for the consolidated Spotify domain service."""

from __future__ import annotations

from app._legacy import warn_legacy_import

from .spotify_domain_service import PlaylistItemsResult, SpotifyDomainService

warn_legacy_import(
    "app.services.spotify_domain",
    "app.services.spotify_domain_service",
)

__all__ = ["SpotifyDomainService", "PlaylistItemsResult"]
