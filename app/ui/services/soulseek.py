"""Soulseek UI service exposing integration status and configuration."""

from __future__ import annotations

from fastapi import Depends, Request

from app.config import AppConfig, SecurityConfig, SoulseekConfig
from app.core.soulseek_client import SoulseekClient
from app.dependencies import (
    get_app_config,
    get_provider_registry,
    get_soulseek_client,
)
from app.integrations.health import IntegrationHealth, ProviderHealthMonitor
from app.integrations.registry import ProviderRegistry
from app.routers.soulseek_router import soulseek_status
from app.schemas import StatusResponse


class SoulseekUiService:
    """Service aggregating Soulseek integration metadata for the UI layer."""

    def __init__(
        self,
        *,
        request: Request,
        config: AppConfig,
        soulseek_client: SoulseekClient,
        registry: ProviderRegistry,
    ) -> None:
        self._request = request
        self._config = config
        self._client = soulseek_client
        self._registry = registry
        self._registry.initialise()
        self._health_monitor = ProviderHealthMonitor(self._registry)

    async def status(self) -> StatusResponse:
        """Return the Soulseek daemon connectivity status."""

        return await soulseek_status(client=self._client)

    async def integration_health(self) -> IntegrationHealth:
        """Return integration health reports for configured providers."""

        return await self._health_monitor.check_all()

    def soulseek_config(self) -> SoulseekConfig:
        """Expose the configured Soulseek settings."""

        return self._config.soulseek

    def security_config(self) -> SecurityConfig:
        """Expose the security profile for UI rendering."""

        return self._config.security


def get_soulseek_ui_service(
    request: Request,
    config: AppConfig = Depends(get_app_config),
    client: SoulseekClient = Depends(get_soulseek_client),
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> SoulseekUiService:
    """FastAPI dependency returning the Soulseek UI service."""

    return SoulseekUiService(
        request=request,
        config=config,
        soulseek_client=client,
        registry=registry,
    )


__all__ = [
    "SoulseekUiService",
    "get_soulseek_ui_service",
]
