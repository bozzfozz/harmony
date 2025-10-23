"""Provider health evaluation utilities."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.integrations.contracts import TrackProvider
from app.integrations.registry import ProviderRegistry
from app.logging import get_logger
from app.logging_events import log_event

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class ProviderHealth:
    """Represents the health state of a single provider."""

    provider: str
    status: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class IntegrationHealth:
    """Aggregated health status across all configured providers."""

    overall: str
    providers: tuple[ProviderHealth, ...]


def _normalise_status(value: str) -> str:
    if not value:
        return "unknown"
    normalised = value.strip().lower()
    if normalised in {"ok", "healthy", "up"}:
        return "ok"
    if normalised in {"degraded", "warning", "partial"}:
        return "degraded"
    if normalised in {"down", "failed", "error"}:
        return "down"
    return normalised


async def _invoke_health(provider: TrackProvider) -> ProviderHealth:
    check = getattr(provider, "check_health", None)
    if check is None:
        detail_payload: MutableMapping[str, Any] = {"reason": "unsupported"}
        return ProviderHealth(provider=provider.name, status="degraded", details=detail_payload)

    try:
        result = check()
        if asyncio.iscoroutine(result):
            result = await result  # type: ignore[assignment]
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning(
            "Provider health check failed",
            exc_info=exc,
            extra={"provider": provider.name},
        )
        return ProviderHealth(
            provider=provider.name,
            status="down",
            details={"reason": "exception", "error": str(exc)},
        )

    status: str
    detail_mapping: Mapping[str, Any]
    if isinstance(result, ProviderHealth):
        status = result.status
        detail_mapping = result.details
    elif isinstance(result, Mapping):
        status = _normalise_status(str(result.get("status", "unknown")))
        raw_details = result.get("details")
        detail_mapping = dict(raw_details) if isinstance(raw_details, Mapping) else {}
    elif isinstance(result, bool):
        status = "ok" if result else "down"
        detail_mapping = {}
    else:
        status = _normalise_status(str(result))
        detail_mapping = {}

    status = _normalise_status(status)
    return ProviderHealth(provider=provider.name, status=status, details=detail_mapping)


def _overall_status(reports: Sequence[ProviderHealth]) -> str:
    if any(report.status == "down" for report in reports):
        return "down"
    if any(report.status == "degraded" for report in reports):
        return "degraded"
    if not reports:
        return "ok"
    return "ok"


class ProviderHealthMonitor:
    """Evaluate health information for providers registered in the system."""

    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    async def check_provider(self, name: str) -> ProviderHealth:
        try:
            provider = self._registry.get_track_provider(name)
        except KeyError:
            return ProviderHealth(provider=name, status="down", details={"reason": "disabled"})
        report = await _invoke_health(provider)
        log_event(
            logger,
            "integration.health",
            component=f"integration.{provider.name}",
            status=report.status,
            meta={"details": dict(report.details)},
        )
        return report

    async def check_all(self) -> IntegrationHealth:
        providers = list(self._registry.track_providers().values())
        reports = await asyncio.gather(*(_invoke_health(provider) for provider in providers))
        overall = _overall_status(reports)
        log_event(
            logger,
            "integration.health",
            component="integration.aggregate",
            status=overall,
            meta={"providers": [report.provider for report in reports]},
        )
        return IntegrationHealth(overall=overall, providers=tuple(reports))


__all__ = ["IntegrationHealth", "ProviderHealth", "ProviderHealthMonitor"]
