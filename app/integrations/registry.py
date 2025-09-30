"""Provider registry that wires configured integrations."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping

from app.config import AppConfig
from app.core.spotify_client import SpotifyClient
from app.integrations.contracts import (
    ProviderAlbum,
    ProviderArtist,
    ProviderDependencyError,
    ProviderInternalError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderTrack,
    ProviderValidationError,
    SearchQuery,
    TrackProvider,
)
from app.integrations.provider_gateway import ProviderGatewayConfig, ProviderRetryPolicy
from app.integrations.plex_adapter import PlexAdapter
from app.integrations.slskd_adapter import (
    SlskdAdapter,
    SlskdAdapterDependencyError,
    SlskdAdapterInternalError,
    SlskdAdapterNotFoundError,
    SlskdAdapterRateLimitedError,
    SlskdAdapterValidationError,
)
from app.integrations.spotify_adapter import SpotifyAdapter
from app.logging import get_logger


logger = get_logger(__name__)


class ProviderRegistry:
    """Factory resolving provider adapters based on feature flags."""

    def __init__(self, *, config: AppConfig) -> None:
        self._config = config
        self._providers: Dict[str, object] = {}
        self._track_providers: Dict[str, TrackProvider] = {}
        self._policies: Dict[str, ProviderRetryPolicy] = {}

    @property
    def gateway_config(self) -> ProviderGatewayConfig:
        default_policy = ProviderRetryPolicy(
            timeout_ms=15_000,
            retry_max=0,
            backoff_base_ms=50,
            jitter_pct=0.1,
        )
        return ProviderGatewayConfig(
            max_concurrency=self._config.integrations.max_concurrency,
            default_policy=default_policy,
            provider_policies=dict(self._policies),
        )

    @property
    def enabled_names(self) -> tuple[str, ...]:
        return self._config.integrations.enabled

    def initialise(self) -> None:
        enabled = OrderedDict.fromkeys(self.enabled_names)
        for name in enabled:
            if name in self._providers:
                continue
            adapter = self._build_adapter(name)
            if adapter is not None:
                self._providers[name] = adapter
                self._register_track_provider(name, adapter)

    def _build_adapter(self, name: str) -> object | None:
        name = name.lower()
        timeouts = self._config.integrations.timeouts_ms
        timeout_ms = timeouts.get(name, 15000)
        if name == "spotify":
            try:
                client = SpotifyClient(self._config.spotify)
            except Exception as exc:  # pragma: no cover - configuration guard
                logger.warning("Spotify adapter disabled: %s", exc)
                return None
            return SpotifyAdapter(client=client, timeout_ms=timeout_ms)
        if name == "plex":
            return PlexAdapter(timeout_ms=timeout_ms)
        if name in {"slskd", "soulseek"}:
            soulseek = self._config.soulseek
            return SlskdAdapter(
                base_url=soulseek.base_url,
                api_key=soulseek.api_key,
                timeout_ms=soulseek.timeout_ms,
                max_retries=soulseek.retry_max,
                backoff_base_ms=soulseek.retry_backoff_base_ms,
                jitter_pct=soulseek.retry_jitter_pct,
                preferred_formats=soulseek.preferred_formats,
                max_results=soulseek.max_results,
            )
        return None

    def _register_track_provider(self, name: str, adapter: object) -> None:
        normalized = name.lower()
        if isinstance(adapter, SlskdAdapter):
            provider = _SlskdTrackProvider(adapter)
            self._track_providers[provider.name] = provider
            soulseek = self._config.soulseek
            timeout = soulseek.timeout_ms
            policy = ProviderRetryPolicy(
                timeout_ms=timeout,
                retry_max=max(0, soulseek.retry_max),
                backoff_base_ms=max(1, soulseek.retry_backoff_base_ms),
                jitter_pct=max(0.0, soulseek.retry_jitter_pct),
            )
            self._policies[provider.name] = policy
        elif isinstance(adapter, SpotifyAdapter):
            provider = _SpotifyTrackProvider(adapter)
            self._track_providers[provider.name] = provider
            timeout_ms = self._config.integrations.timeouts_ms.get("spotify", 15000)
            self._policies[provider.name] = ProviderRetryPolicy(
                timeout_ms=timeout_ms,
                retry_max=0,
                backoff_base_ms=50,
                jitter_pct=0.1,
            )
        elif normalized in self._config.integrations.timeouts_ms:
            timeout_ms = self._config.integrations.timeouts_ms[normalized]
            self._policies[normalized] = ProviderRetryPolicy(
                timeout_ms=timeout_ms,
                retry_max=0,
                backoff_base_ms=50,
                jitter_pct=0.1,
            )

    def get(self, name: str) -> object:
        normalized = name.lower()
        if normalized not in self._providers:
            raise KeyError(f"Provider {name!r} is not enabled")
        return self._providers[normalized]

    def all(self) -> Iterable[object]:
        return tuple(
            self._providers[name] for name in self.enabled_names if name in self._providers
        )

    def track_providers(self) -> Mapping[str, TrackProvider]:
        return dict(self._track_providers)

    def get_track_provider(self, name: str) -> TrackProvider:
        normalized = name.lower()
        if normalized not in self._track_providers:
            raise KeyError(f"Track provider {name!r} is not enabled")
        return self._track_providers[normalized]


@dataclass(slots=True)
class _SlskdTrackProvider(TrackProvider):
    _adapter: SlskdAdapter

    @property
    def name(self) -> str:  # pragma: no cover - simple delegation
        return "slskd"

    async def search_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        try:
            candidates = await self._adapter.search_tracks(
                query.text,
                artist=query.artist,
                limit=query.limit,
            )
        except SlskdAdapterValidationError as exc:
            raise ProviderValidationError(
                self.name,
                str(exc),
                status_code=exc.status_code,
                cause=exc,
            ) from exc
        except SlskdAdapterRateLimitedError as exc:
            raise ProviderRateLimitedError(
                self.name,
                "slskd rate limited the request",
                retry_after_ms=exc.retry_after_ms,
                retry_after_header=exc.retry_after_header,
                cause=exc,
            ) from exc
        except SlskdAdapterNotFoundError as exc:
            raise ProviderNotFoundError(
                self.name,
                "slskd returned no results",
                status_code=exc.status_code,
                cause=exc,
            ) from exc
        except SlskdAdapterDependencyError as exc:
            raise ProviderDependencyError(
                self.name,
                "slskd dependency error",
                status_code=exc.status_code,
                cause=exc,
            ) from exc
        except SlskdAdapterInternalError as exc:
            raise ProviderInternalError(self.name, "slskd internal error", cause=exc) from exc
        except Exception as exc:  # pragma: no cover - defensive guard
            raise ProviderInternalError(self.name, "slskd unexpected error", cause=exc) from exc

        tracks: list[ProviderTrack] = []
        for candidate in candidates:
            artists = (ProviderArtist(name=candidate.artist),) if candidate.artist else ()
            tracks.append(
                ProviderTrack(
                    name=candidate.title,
                    provider=self.name,
                    artists=artists,
                    candidates=(candidate,),
                )
            )
        return tracks


@dataclass(slots=True)
class _SpotifyTrackProvider(TrackProvider):
    _adapter: SpotifyAdapter

    @property
    def name(self) -> str:  # pragma: no cover - simple delegation
        return "spotify"

    async def search_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        limit = max(1, query.limit)

        def _search() -> list:
            return list(self._adapter.search_tracks(query.text, limit=limit))

        tracks = await asyncio.to_thread(_search)
        results: list[ProviderTrack] = []
        for track in tracks:
            artist_entries: list[ProviderArtist] = []
            aggregated_genres: set[str] = set()
            for artist in getattr(track, "artists", ()):
                metadata: dict[str, object] = {}
                artist_id = getattr(artist, "id", None)
                if getattr(artist, "genres", None):
                    genres = tuple(str(entry) for entry in artist.genres if entry)
                    if genres:
                        metadata["genres"] = genres
                        aggregated_genres.update(genres)
                popularity = getattr(artist, "popularity", None)
                if popularity is not None:
                    metadata["popularity"] = popularity
                artist_entries.append(
                    ProviderArtist(
                        name=getattr(artist, "name", ""),
                        id=artist_id,
                        metadata=metadata,
                    )
                )
            album = None
            if getattr(track, "album", None) is not None:
                album_artists: list[ProviderArtist] = []
                album_metadata: dict[str, object] = {}
                for artist in track.album.artists:
                    album_artist_metadata: dict[str, object] = {}
                    if getattr(artist, "genres", None):
                        album_artist_metadata["genres"] = tuple(
                            str(entry) for entry in artist.genres if entry
                        )
                    album_artists.append(
                        ProviderArtist(
                            name=getattr(artist, "name", ""),
                            id=getattr(artist, "id", None),
                            metadata=album_artist_metadata,
                        )
                    )
                if getattr(track.album, "release_year", None) is not None:
                    album_metadata["release_year"] = track.album.release_year
                if getattr(track.album, "total_tracks", None) is not None:
                    album_metadata["total_tracks"] = track.album.total_tracks
                album = ProviderAlbum(
                    name=getattr(track.album, "name", ""),
                    id=getattr(track.album, "id", None),
                    artists=tuple(album_artists),
                    metadata=album_metadata,
                )
            track_metadata: dict[str, object] = {}
            track_id = getattr(track, "id", None)
            if track_id is not None:
                track_metadata["id"] = track_id
            if getattr(track, "duration_ms", None) is not None:
                track_metadata["duration_ms"] = track.duration_ms
            if getattr(track, "isrc", None):
                track_metadata["isrc"] = track.isrc
            if aggregated_genres:
                track_metadata["genres"] = tuple(aggregated_genres)
            results.append(
                ProviderTrack(
                    name=getattr(track, "name", ""),
                    provider=self.name,
                    artists=tuple(artist_entries),
                    album=album,
                    duration_ms=getattr(track, "duration_ms", None),
                    isrc=getattr(track, "isrc", None),
                    candidates=(),
                    metadata=track_metadata,
                )
            )
        return results
