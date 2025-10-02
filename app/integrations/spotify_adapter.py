"""Spotify track provider implementation."""

from __future__ import annotations

import asyncio
from typing import Any, Iterable

from app.core.spotify_client import SpotifyClient
from app.integrations.contracts import (
    ProviderDependencyError,
    ProviderInternalError,
    ProviderTrack,
    SearchQuery,
    TrackProvider,
)
from app.integrations.normalizers import normalize_spotify_track
from app.logging import get_logger


logger = get_logger(__name__)


def _iter_track_items(payload: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    tracks_payload = payload.get("tracks")
    if not isinstance(tracks_payload, dict):
        return []
    items = tracks_payload.get("items")
    if not isinstance(items, list):
        return []
    return [entry for entry in items if isinstance(entry, dict)]


class SpotifyAdapter(TrackProvider):
    """Adapter using :class:`SpotifyClient` for integration flows."""

    name = "spotify"

    def __init__(self, *, client: SpotifyClient, result_cap: int = 50) -> None:
        self._client = client
        self._result_cap = max(1, result_cap)

    async def search_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        effective_limit = max(1, min(query.limit, self._result_cap))

        def _search() -> list[ProviderTrack]:
            try:
                payload = self._client.search_tracks(query.text, limit=effective_limit)
            except Exception as exc:  # pragma: no cover - network errors mocked in tests
                raise ProviderDependencyError(
                    self.name, "spotify search failed", cause=exc
                ) from exc

            results: list[ProviderTrack] = []
            for item in _iter_track_items(payload):
                try:
                    results.append(normalize_spotify_track(item, provider=self.name))
                except Exception as exc:  # pragma: no cover - defensive guard
                    logger.warning("Failed to normalise Spotify track", exc_info=exc)
            return results

        try:
            return await asyncio.to_thread(_search)
        except ProviderDependencyError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            raise ProviderInternalError(self.name, "spotify search failed") from exc


__all__ = ["SpotifyAdapter"]
