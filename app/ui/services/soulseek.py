"""Soulseek UI service exposing integration status and configuration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

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
from app.logging import get_logger
from app.routers.soulseek_router import (
    soulseek_all_uploads,
    soulseek_cancel_upload,
    soulseek_status,
    soulseek_uploads,
)
from app.schemas import StatusResponse


logger = get_logger(__name__)


@dataclass(slots=True)
class SoulseekUploadRow:
    """Lightweight representation of an active Soulseek upload."""

    identifier: str
    filename: str
    status: str
    progress: float | None
    size_bytes: int | None
    speed_bps: float | None
    username: str | None


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

    async def uploads(self, *, include_all: bool = False) -> Sequence[SoulseekUploadRow]:
        """Return normalised upload rows for the requested scope."""

        if include_all:
            payload = await soulseek_all_uploads(client=self._client)
        else:
            payload = await soulseek_uploads(client=self._client)
        uploads_raw = self._extract_uploads(payload)
        rows: list[SoulseekUploadRow] = []
        for entry in uploads_raw:
            row = self._to_row(entry)
            if row is not None:
                rows.append(row)
        logger.debug(
            "soulseek.ui.uploads",  # structured logging for observability
            extra={
                "include_all": include_all,
                "count": len(rows),
            },
        )
        return tuple(rows)

    async def cancel_upload(self, *, upload_id: str) -> None:
        """Cancel an upload through the Soulseek router."""

        if not upload_id:
            raise ValueError("upload_id is required")
        await soulseek_cancel_upload(upload_id=upload_id, client=self._client)
        logger.info(
            "soulseek.ui.upload.cancelled",
            extra={"upload_id": upload_id},
        )

    @staticmethod
    def _extract_uploads(payload: Any) -> Sequence[Any]:
        if isinstance(payload, dict):
            uploads = payload.get("uploads")
            if isinstance(uploads, list):
                return uploads
            if isinstance(uploads, dict):
                return [uploads]
            return []
        if isinstance(payload, list):
            return payload
        return []

    @staticmethod
    def _to_row(entry: Any) -> SoulseekUploadRow | None:
        if not isinstance(entry, dict):
            return None
        identifier = str(
            entry.get("id")
            or entry.get("token")
            or entry.get("identifier")
            or entry.get("filename")
            or entry.get("path")
            or "unknown"
        ).strip()
        if not identifier:
            identifier = "unknown"
        progress = SoulseekUiService._coerce_progress(entry.get("progress"))
        size_value = SoulseekUiService._coerce_int(entry.get("size"))
        speed_value = SoulseekUiService._coerce_float(entry.get("speed"))
        username = entry.get("username") or entry.get("user")
        filename = entry.get("filename") or entry.get("path") or entry.get("file") or ""
        status_raw = entry.get("status") or entry.get("state") or "unknown"
        status = str(status_raw) if status_raw is not None else "unknown"
        return SoulseekUploadRow(
            identifier=identifier,
            filename=str(filename),
            status=status,
            progress=progress,
            size_bytes=size_value,
            speed_bps=speed_value,
            username=str(username) if username is not None else None,
        )

    @staticmethod
    def _coerce_progress(value: Any) -> float | None:
        if isinstance(value, (int, float)):
            numeric = float(value)
            if numeric > 1:
                numeric = numeric / 100.0
            if numeric < 0:
                return 0.0
            if numeric > 1:
                return 1.0
            return numeric
        if isinstance(value, str):
            stripped = value.strip().rstrip("%")
            try:
                numeric = float(stripped)
            except ValueError:
                return None
            if "%" in value or numeric > 1:
                numeric /= 100.0
            numeric = max(0.0, min(numeric, 1.0))
            return numeric
        return None

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return int(float(stripped))
            except ValueError:
                return None
        return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return float(stripped)
            except ValueError:
                return None
        return None


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
    "SoulseekUploadRow",
    "get_soulseek_ui_service",
]
