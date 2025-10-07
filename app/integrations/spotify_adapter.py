"""Spotify track provider implementation."""

from __future__ import annotations

import asyncio
from typing import Any, Iterable, Mapping

from app.core.spotify_client import SpotifyClient
from app.integrations.contracts import (
    ProviderArtist,
    ProviderDependencyError,
    ProviderInternalError,
    ProviderNotFoundError,
    ProviderRelease,
    ProviderTrack,
    ProviderValidationError,
    SearchQuery,
    TrackProvider,
)
from app.integrations.normalizers import (
    from_spotify_artist,
    from_spotify_release,
    normalize_spotify_track,
)
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

    async def fetch_artist(
        self, *, artist_id: str | None = None, name: str | None = None
    ) -> ProviderArtist | None:
        identifier = (artist_id or "").strip()
        query_name = (name or "").strip()
        if not identifier and not query_name:
            raise ProviderValidationError(
                self.name,
                "artist_id or name must be provided",
                status_code=400,
            )

        def _select_by_name(value: str) -> Any:
            response = self._client.search_artists(value, limit=1)
            if not isinstance(response, dict):
                return None
            container = response.get("artists")
            items: Iterable[Any]
            if isinstance(container, dict):
                items = container.get("items") or []
            else:
                items = response.get("items") or []
            if not isinstance(items, list):
                return None
            for entry in items:
                if isinstance(entry, dict):
                    return entry
            return None

        def _load() -> ProviderArtist:
            try:
                payload: Any
                if identifier:
                    payload = self._client.get_artist(identifier)
                else:
                    payload = _select_by_name(query_name)
            except Exception as exc:  # pragma: no cover - network errors mocked in tests
                raise ProviderDependencyError(
                    self.name, "spotify artist lookup failed", cause=exc
                ) from exc

            if not payload:
                raise ProviderNotFoundError(self.name, "artist not found", status_code=404)

            try:
                return from_spotify_artist(payload)
            except ValueError as exc:
                raise ProviderInternalError(self.name, "invalid artist payload") from exc

        try:
            return await asyncio.to_thread(_load)
        except ProviderDependencyError:
            raise
        except ProviderNotFoundError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            raise ProviderInternalError(self.name, "spotify artist lookup failed") from exc

    async def fetch_artist_releases(
        self, artist_source_id: str, *, limit: int | None = None
    ) -> list[ProviderRelease]:
        identifier = (artist_source_id or "").strip()
        if not identifier:
            raise ProviderValidationError(
                self.name,
                "artist_source_id must not be empty",
                status_code=400,
            )

        max_items = None
        if limit is not None:
            try:
                max_items = max(1, int(limit))
            except (TypeError, ValueError):
                max_items = None

        def _load() -> list[ProviderRelease]:
            try:
                payload = self._client.get_artist_releases(identifier)
            except Exception as exc:  # pragma: no cover - network errors mocked in tests
                raise ProviderDependencyError(
                    self.name, "spotify artist releases failed", cause=exc
                ) from exc

            items: list[Mapping[str, Any]] = []
            if isinstance(payload, dict):
                candidates: Iterable[Any] = ()
                if isinstance(payload.get("items"), list):
                    candidates = payload["items"]
                elif isinstance(payload.get("albums"), list):
                    candidates = payload["albums"]
                elif isinstance(payload.get("releases"), list):
                    candidates = payload["releases"]
                for entry in candidates:
                    if isinstance(entry, dict):
                        items.append(entry)
            elif isinstance(payload, list):
                items = [entry for entry in payload if isinstance(entry, dict)]

            releases: list[ProviderRelease] = []
            seen: set[tuple[str | None, str]] = set()
            for entry in items:
                try:
                    release = from_spotify_release(entry, identifier)
                except ValueError:
                    continue
                key = (release.source_id, release.title)
                if key in seen:
                    continue
                seen.add(key)
                releases.append(release)
                if max_items is not None and len(releases) >= max_items:
                    break
            return releases

        try:
            return await asyncio.to_thread(_load)
        except ProviderDependencyError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            raise ProviderInternalError(self.name, "spotify artist releases failed") from exc


__all__ = ["SpotifyAdapter"]
