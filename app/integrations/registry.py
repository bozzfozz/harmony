"""Provider registry that wires configured integrations."""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, Iterable

from app.config import AppConfig
from app.core.spotify_client import SpotifyClient
from app.integrations.base import MusicProvider
from app.integrations.plex_adapter import PlexAdapter
from app.integrations.slskd_adapter import SlskdAdapter
from app.integrations.slskd_client import SlskdHttpClient
from app.integrations.spotify_adapter import SpotifyAdapter
from app.logging import get_logger


logger = get_logger(__name__)


class ProviderRegistry:
    """Factory resolving provider adapters based on feature flags."""

    def __init__(self, *, config: AppConfig) -> None:
        self._config = config
        self._providers: Dict[str, MusicProvider] = {}

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

    def _build_adapter(self, name: str) -> MusicProvider | None:
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
            client = SlskdHttpClient(base_url=soulseek.base_url, api_key=soulseek.api_key)
            fallback_ms = self._config.integrations.slskd_rate_limit_retry_after_fallback_ms
            return SlskdAdapter(
                client=client,
                timeout_ms=timeout_ms,
                rate_limit_fallback_ms=fallback_ms,
            )
        return None

    def get(self, name: str) -> MusicProvider:
        normalized = name.lower()
        if normalized not in self._providers:
            raise KeyError(f"Provider {name!r} is not enabled")
        return self._providers[normalized]

    def all(self) -> Iterable[MusicProvider]:
        return tuple(
            self._providers[name] for name in self.enabled_names if name in self._providers
        )
