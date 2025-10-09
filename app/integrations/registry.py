"""Registry for integration providers."""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, Mapping

from app.config import AppConfig
from app.core.spotify_client import SpotifyClient
from app.integrations.contracts import TrackProvider
from app.integrations.provider_gateway import ProviderGatewayConfig, ProviderRetryPolicy
from app.integrations.slskd_adapter import SlskdAdapter
from app.integrations.spotify_adapter import SpotifyAdapter
from app.logging import get_logger

logger = get_logger(__name__)


class ProviderRegistry:
    """Factory resolving provider adapters based on feature flags."""

    def __init__(self, *, config: AppConfig) -> None:
        self._config = config
        self._providers: Dict[str, TrackProvider] = {}
        self._policies: Dict[str, ProviderRetryPolicy] = {}
        self._initialised = False

    @property
    def gateway_config(self) -> ProviderGatewayConfig:
        base_config = ProviderGatewayConfig.from_settings(
            max_concurrency=self._config.integrations.max_concurrency,
        )
        provider_policies: dict[str, ProviderRetryPolicy] = dict(
            base_config.provider_policies
        )
        provider_policies.update(self._policies)
        return ProviderGatewayConfig(
            max_concurrency=base_config.max_concurrency,
            default_policy=base_config.default_policy,
            provider_policies=provider_policies,
        )

    @property
    def enabled_names(self) -> tuple[str, ...]:
        return self._config.integrations.enabled

    def initialise(self) -> None:
        if self._initialised:
            return
        enabled = OrderedDict.fromkeys(self.enabled_names)
        for name in enabled:
            provider = self._build_track_provider(name)
            if provider is None:
                continue
            self._providers[provider.name] = provider
            self._policies[provider.name] = self._policy_for(provider.name)
        self._initialised = True

    def _build_track_provider(self, name: str) -> TrackProvider | None:
        normalized = name.lower()
        if normalized == "spotify":
            try:
                client = SpotifyClient(self._config.spotify)
            except Exception as exc:  # pragma: no cover - configuration guard
                logger.warning("Spotify adapter disabled: %s", exc)
                return None
            return SpotifyAdapter(client=client)
        if normalized in {"slskd", "soulseek"}:
            soulseek = self._config.soulseek
            return SlskdAdapter(
                base_url=soulseek.base_url,
                api_key=soulseek.api_key,
                timeout_ms=soulseek.timeout_ms,
                preferred_formats=soulseek.preferred_formats,
                max_results=soulseek.max_results,
            )
        return None

    def _policy_for(self, name: str) -> ProviderRetryPolicy:
        normalized = name.lower()
        if normalized in {"slskd", "soulseek"}:
            soulseek = self._config.soulseek
            return ProviderRetryPolicy(
                timeout_ms=soulseek.timeout_ms,
                retry_max=max(0, soulseek.retry_max),
                backoff_base_ms=max(1, soulseek.retry_backoff_base_ms),
                jitter_pct=max(0.0, soulseek.retry_jitter_pct),
            )
        timeout_ms = self._config.integrations.timeouts_ms.get(normalized, 15000)
        return ProviderRetryPolicy(
            timeout_ms=timeout_ms,
            retry_max=0,
            backoff_base_ms=100,
            jitter_pct=0.1,
        )

    def track_providers(self) -> Mapping[str, TrackProvider]:
        if not self._initialised:
            self.initialise()
        return dict(self._providers)

    def get_track_provider(self, name: str) -> TrackProvider:
        if not self._initialised:
            self.initialise()
        normalized = name.lower()
        if normalized not in self._providers:
            raise KeyError(f"Track provider {name!r} is not enabled")
        return self._providers[normalized]


__all__ = ["ProviderRegistry"]
