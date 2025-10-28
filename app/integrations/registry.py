"""Registry for integration providers."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
import inspect
from typing import Final

from app.config import AppConfig
from app.core.spotify_client import SpotifyClient
from app.integrations.contracts import TrackProvider
from app.integrations.provider_gateway import ProviderGatewayConfig, ProviderRetryPolicy
from app.integrations.slskd_adapter import SlskdAdapter
from app.integrations.spotify_adapter import SpotifyAdapter
from app.logging import get_logger

logger = get_logger(__name__)


_ShutdownCallback = Callable[[], Awaitable[None] | None]


_PROVIDER_ALIASES: Final[dict[str, str]] = {
    "soulseek": "slskd",
}


class _AdapterShutdownManager:
    """Manage adapter shutdown callbacks safely and idempotently."""

    def __init__(self) -> None:
        self._callbacks: list[tuple[str, _ShutdownCallback]] = []
        self._shutdown_started = False

    def register(self, provider: str, callback: _ShutdownCallback) -> None:
        if self._shutdown_started:
            logger.warning(
                "Late registration of provider shutdown callback ignored",
                extra={"event": "provider.shutdown.late_registration", "provider": provider},
            )
            return
        self._callbacks.append((provider, callback))

    async def shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        try:
            for provider, callback in self._callbacks:
                try:
                    result = callback()
                    if inspect.isawaitable(result):
                        await result
                except Exception:  # pragma: no cover - defensive guard
                    logger.exception(
                        "Error while shutting down provider adapter",
                        extra={"event": "provider.shutdown.error", "provider": provider},
                    )
        finally:
            self._callbacks.clear()


class ProviderRegistry:
    """Factory resolving provider adapters based on feature flags."""

    def __init__(self, *, config: AppConfig) -> None:
        self._config = config
        self._providers: dict[str, TrackProvider] = {}
        self._policies: dict[str, ProviderRetryPolicy] = {}
        self._initialised = False
        self._shutdown_manager = _AdapterShutdownManager()

    @property
    def gateway_config(self) -> ProviderGatewayConfig:
        base_config = ProviderGatewayConfig.from_settings(
            max_concurrency=self._config.integrations.max_concurrency,
        )
        provider_policies: dict[str, ProviderRetryPolicy] = dict(base_config.provider_policies)
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
            normalized = name.lower()
            canonical_key = self._canonical_name_for(normalized)
            provider = self._providers.get(canonical_key)
            policy = self._policies.get(canonical_key)
            if provider is None:
                provider = self._build_track_provider(normalized)
                if provider is None:
                    continue
                canonical_key = provider.name
                policy = self._policy_for(canonical_key)
                self._providers[canonical_key] = provider
                self._policies[canonical_key] = policy
                self._register_shutdown_callback(provider)
            elif policy is None:
                policy = self._policy_for(canonical_key)
                self._policies[canonical_key] = policy

            self._providers[normalized] = provider
            if policy is not None:
                self._policies[normalized] = policy
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
        provider = self._providers.get(normalized)
        if provider is not None:
            return provider

        canonical = self._canonical_name_for(normalized)
        provider = self._providers.get(canonical)
        if provider is None:
            raise KeyError(f"Track provider {name!r} is not enabled")

        self._providers[normalized] = provider
        policy = self._policies.get(canonical)
        if policy is None:
            policy = self._policy_for(canonical)
            self._policies[canonical] = policy
        self._policies[normalized] = policy
        return provider

    async def shutdown(self) -> None:
        """Close all registered providers, ignoring repeated calls."""

        await self._shutdown_manager.shutdown()

    def _register_shutdown_callback(self, provider: TrackProvider) -> None:
        close_callable = getattr(provider, "aclose", None)
        if close_callable is None or not callable(close_callable):
            return

        def _callback() -> Awaitable[None] | None:
            return close_callable()

        self._shutdown_manager.register(provider.name, _callback)

    def _canonical_name_for(self, name: str) -> str:
        normalized = name.lower()
        return _PROVIDER_ALIASES.get(normalized, normalized)


__all__ = ["ProviderRegistry"]
