"""Gateway orchestrating artist metadata calls via :mod:`ProviderGateway`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from app.integrations.contracts import SearchQuery
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewayDependencyError,
    ProviderGatewayError,
    ProviderGatewayRateLimitedError,
    ProviderGatewaySearchResult,
    ProviderGatewayTimeoutError,
)


@dataclass(slots=True, frozen=True)
class ArtistReleaseDTO:
    """Normalised representation of a provider release payload."""

    id: str
    etag: str | None = None
    fetched_at: datetime | None = None
    provider_cursor: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ArtistDTO:
    """Normalised representation of an artist with release information."""

    id: str
    etag: str | None = None
    fetched_at: datetime | None = None
    provider_cursor: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    releases: tuple[ArtistReleaseDTO, ...] = ()


@dataclass(slots=True, frozen=True)
class ArtistGatewayResult:
    """Container describing the outcome of a provider specific fetch."""

    provider: str
    artist: ArtistDTO | None
    releases: tuple[ArtistReleaseDTO, ...]
    error: ProviderGatewayError | None = None
    retryable: bool = False


@dataclass(slots=True, frozen=True)
class ArtistGatewayResponse:
    """Aggregated response for multi-provider artist fetch operations."""

    artist_id: str
    results: tuple[ArtistGatewayResult, ...]

    @property
    def releases(self) -> tuple[ArtistReleaseDTO, ...]:
        """Return the deduplicated set of releases across providers."""

        seen: dict[str, ArtistReleaseDTO] = {}
        for result in self.results:
            for release in result.releases:
                seen[release.id] = release
        return tuple(seen.values())

    @property
    def errors(self) -> Mapping[str, ProviderGatewayError]:
        return {
            result.provider: result.error
            for result in self.results
            if result.error is not None
        }

    @property
    def retryable(self) -> bool:
        return any(result.retryable for result in self.results if result.error)


class ArtistGateway:
    """Facade providing release lookups while reusing provider gateway policies."""

    def __init__(self, *, provider_gateway: ProviderGateway) -> None:
        self._provider_gateway = provider_gateway

    async def fetch_artist(
        self,
        artist_id: str,
        *,
        providers: Sequence[str],
        limit: int = 50,
    ) -> ArtistGatewayResponse:
        """Fetch artist releases from the configured providers."""

        effective_limit = max(1, int(limit))
        query = SearchQuery(text=artist_id, artist=artist_id, limit=effective_limit)
        response = await self._provider_gateway.search_many(providers, query)
        results = tuple(self._normalise_result(entry) for entry in response.results)
        return ArtistGatewayResponse(artist_id=artist_id, results=results)

    def _normalise_result(self, result: ProviderGatewaySearchResult) -> ArtistGatewayResult:
        artist, releases = self._extract_payload(result)
        error = result.error
        retryable = self._is_retryable(error)
        return ArtistGatewayResult(
            provider=result.provider,
            artist=artist,
            releases=releases,
            error=error,
            retryable=retryable,
        )

    def _extract_payload(
        self, result: ProviderGatewaySearchResult
    ) -> tuple[ArtistDTO | None, tuple[ArtistReleaseDTO, ...]]:
        artist: ArtistDTO | None = None
        releases: list[ArtistReleaseDTO] = []
        for track in result.tracks:
            metadata = getattr(track, "metadata", None)
            if not isinstance(metadata, Mapping):
                continue
            artist_payload = metadata.get("artist")
            if artist is None and isinstance(artist_payload, Mapping):
                try:
                    artist = self._normalise_artist(artist_payload)
                except ValueError:
                    artist = None
            releases_payload = metadata.get("releases")
            if isinstance(releases_payload, Mapping):
                releases_payload = [releases_payload]
            if isinstance(releases_payload, Sequence) and not isinstance(
                releases_payload, (str, bytes)
            ):
                for entry in releases_payload:
                    if isinstance(entry, Mapping):
                        normalized = self._normalise_release(entry)
                        if normalized is not None:
                            releases.append(normalized)
            release_payload = metadata.get("release")
            if isinstance(release_payload, Mapping):
                normalized = self._normalise_release(release_payload)
                if normalized is not None:
                    releases.append(normalized)
        deduped: dict[str, ArtistReleaseDTO] = {}
        for release in releases:
            deduped[release.id] = release
        if artist is not None and not artist.releases and deduped:
            artist = ArtistDTO(
                id=artist.id,
                etag=artist.etag,
                fetched_at=artist.fetched_at,
                provider_cursor=artist.provider_cursor,
                metadata=artist.metadata,
                releases=tuple(deduped.values()),
            )
        return artist, tuple(deduped.values())

    def _normalise_artist(self, payload: Mapping[str, object]) -> ArtistDTO:
        raw_id = payload.get("id")
        if raw_id is None or raw_id == "":
            raise ValueError("artist payload missing 'id'")
        artist_id = str(raw_id)
        etag = self._optional_str(payload.get("etag"))
        fetched_at = self._coerce_datetime(payload.get("fetched_at"))
        cursor = self._optional_str(payload.get("provider_cursor") or payload.get("cursor"))
        metadata = self._extract_metadata(payload, {"id", "etag", "fetched_at", "provider_cursor", "cursor", "releases"})
        releases_payload = payload.get("releases")
        releases: tuple[ArtistReleaseDTO, ...] = ()
        if isinstance(releases_payload, Mapping):
            releases_payload = [releases_payload]
        if isinstance(releases_payload, Sequence) and not isinstance(
            releases_payload, (str, bytes)
        ):
            releases = tuple(
                normalized
                for entry in releases_payload
                if isinstance(entry, Mapping)
                for normalized in [self._normalise_release(entry)]
                if normalized is not None
            )
        return ArtistDTO(
            id=artist_id,
            etag=etag,
            fetched_at=fetched_at,
            provider_cursor=cursor,
            metadata=metadata,
            releases=releases,
        )

    def _normalise_release(self, payload: Mapping[str, object]) -> ArtistReleaseDTO | None:
        release_id = payload.get("id")
        if release_id is None or release_id == "":
            return None
        etag = self._optional_str(payload.get("etag"))
        fetched_at = self._coerce_datetime(payload.get("fetched_at"))
        cursor = self._optional_str(payload.get("provider_cursor") or payload.get("cursor"))
        metadata = self._extract_metadata(
            payload,
            {"id", "etag", "fetched_at", "provider_cursor", "cursor"},
        )
        return ArtistReleaseDTO(
            id=str(release_id),
            etag=etag,
            fetched_at=fetched_at,
            provider_cursor=cursor,
            metadata=metadata,
        )

    @staticmethod
    def _optional_str(value: object) -> str | None:
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _extract_metadata(
        payload: Mapping[str, object], keys: set[str]
    ) -> Mapping[str, object]:
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            return dict(metadata)
        extracted: dict[str, object] = {}
        for key, value in payload.items():
            if key in keys:
                continue
            extracted[key] = value
        return extracted

    @staticmethod
    def _coerce_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                if value.endswith("Z"):
                    value = value[:-1] + "+00:00"
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _is_retryable(error: ProviderGatewayError | None) -> bool:
        if error is None:
            return False
        return isinstance(
            error,
            (
                ProviderGatewayTimeoutError,
                ProviderGatewayRateLimitedError,
                ProviderGatewayDependencyError,
            ),
        )


__all__ = [
    "ArtistGateway",
    "ArtistGatewayResponse",
    "ArtistGatewayResult",
    "ArtistDTO",
    "ArtistReleaseDTO",
]

