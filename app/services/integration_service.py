"""Service orchestrating calls across configured music providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from app.integrations.base import MusicProvider, ProviderError, Track
from app.integrations.registry import ProviderRegistry


@dataclass(slots=True)
class ProviderHealth:
    name: str
    enabled: bool
    health: str


class IntegrationService:
    """Expose high level operations across configured music providers."""

    def __init__(self, *, registry: ProviderRegistry) -> None:
        self._registry = registry
        self._registry.initialise()

    def search_tracks(
        self, query: str, *, limit: int = 20, providers: Sequence[str] | None = None
    ) -> tuple[list[tuple[str, Track]], dict[str, str]]:
        names = tuple(providers) if providers else self._registry.enabled_names
        results: list[tuple[str, Track]] = []
        failures: dict[str, str] = {}
        for name in names:
            try:
                adapter = self._registry.get(name)
            except KeyError:
                failures[name] = "provider-disabled"
                continue
            try:
                tracks = list(adapter.search_tracks(query, limit=limit))
            except ProviderError as exc:
                failures[name] = exc.message
                continue
            except Exception as exc:  # pragma: no cover - defensive
                failures[name] = str(exc)
                continue
            for track in tracks:
                results.append((adapter.name, track))
        return results, failures

    def providers(self) -> Iterable[MusicProvider]:
        return self._registry.all()

    def health(self) -> list[ProviderHealth]:
        status: list[ProviderHealth] = []
        enabled = set(self._registry.enabled_names)
        for name in enabled:
            try:
                provider = self._registry.get(name)
            except KeyError:
                status.append(ProviderHealth(name=name, enabled=False, health="disabled"))
                continue
            status.append(ProviderHealth(name=provider.name, enabled=True, health="ok"))
        return status
