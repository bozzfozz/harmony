"""System diagnostics service translating API payloads for UI consumption."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from json import JSONDecodeError, loads
from typing import TYPE_CHECKING

from fastapi import Depends, Request
from sqlalchemy.orm import Session
from starlette.responses import Response as StarletteResponse

from app.api import health as health_api, system as system_api
from app.db import SessionFactory, run_session
from app.dependencies import get_integration_service
from app.errors import AppError, ErrorCode
from app.logging import get_logger
from app.routers import integrations as integrations_router
from app.services.integration_service import IntegrationService

try:
    from app.utils.service_health import evaluate_all_service_health
except Exception:  # pragma: no cover - optional dependency
    evaluate_all_service_health = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from app.utils.service_health import ServiceHealth

logger = get_logger(__name__)


@dataclass(slots=True)
class LivenessRecord:
    status: str
    ok: bool
    version: str | None
    uptime_seconds: float | None


@dataclass(slots=True)
class ReadinessDependency:
    name: str
    status: str


@dataclass(slots=True)
class ReadinessRecord:
    ok: bool
    database: str | None
    dependencies: Sequence[ReadinessDependency]
    orchestrator_components: Sequence[ReadinessDependency]
    orchestrator_jobs: Sequence[ReadinessDependency]
    enabled_jobs: Mapping[str, bool]
    error_message: str | None


@dataclass(slots=True)
class IntegrationProviderStatus:
    name: str
    status: str
    details: Mapping[str, object] | None = None


@dataclass(slots=True)
class IntegrationSummary:
    overall: str
    providers: Sequence[IntegrationProviderStatus]


@dataclass(slots=True)
class SecretValidationRecord:
    provider: str
    mode: str
    valid: bool
    validated_at: datetime
    reason: str | None
    note: str | None


@dataclass(slots=True)
class ServiceHealthBadge:
    service: str
    status: str
    missing: Sequence[str]
    optional_missing: Sequence[str]


async def _load_service_health_evaluations() -> Mapping[str, ServiceHealth]:
    if evaluate_all_service_health is None:
        return {}

    def _evaluate(session: Session) -> Mapping[str, ServiceHealth]:
        return dict(evaluate_all_service_health(session))

    return await run_session(_evaluate)


class SystemUiService:
    """Facade delegating to health, system and integrations modules."""

    def __init__(self, integration_service: IntegrationService) -> None:
        self._integration_service = integration_service

    async def fetch_liveness(self, request: Request) -> LivenessRecord:
        try:
            live_payload = await health_api.live()
            system_payload = await system_api.get_health(request)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("system.ui.liveness.error")
            raise AppError(
                "Unable to load liveness information.",
                code=ErrorCode.DEPENDENCY_ERROR,
            ) from exc

        status_text = str(live_payload.get("status", "unknown"))
        data = system_payload.get("data") if isinstance(system_payload, Mapping) else None
        version = str(data.get("version")) if isinstance(data, Mapping) else None
        uptime_raw = data.get("uptime_s") if isinstance(data, Mapping) else None
        if isinstance(uptime_raw, int | float):
            uptime_seconds = float(uptime_raw)
        else:
            uptime_seconds = None
        ok = status_text.lower() == "ok"
        return LivenessRecord(
            status=status_text,
            ok=ok,
            version=version,
            uptime_seconds=uptime_seconds,
        )

    async def fetch_readiness(self, request: Request) -> ReadinessRecord:
        try:
            payload = await system_api.get_readiness(request)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("system.ui.readiness.error")
            raise AppError(
                "Unable to load readiness information.",
                code=ErrorCode.DEPENDENCY_ERROR,
            ) from exc

        if isinstance(payload, StarletteResponse):
            payload = self._decode_response_payload(payload)

        ok = bool(payload.get("ok"))
        error_message: str | None = None
        if not ok:
            error = payload.get("error") if isinstance(payload, Mapping) else None
            if isinstance(error, Mapping):
                error_message = str(error.get("message") or "Readiness check failed.")
            else:
                error_message = "Readiness check failed."

        data = payload.get("data") if isinstance(payload, Mapping) else None
        database = None
        dependencies: list[ReadinessDependency] = []
        orchestrator_components: list[ReadinessDependency] = []
        orchestrator_jobs: list[ReadinessDependency] = []
        enabled_jobs: Mapping[str, bool] = {}

        if isinstance(data, Mapping):
            database = str(data.get("db")) if data.get("db") is not None else None
            deps = data.get("deps") if isinstance(data.get("deps"), Mapping) else {}
            for name, status_text in sorted(deps.items()):
                dependencies.append(
                    ReadinessDependency(name=str(name), status=str(status_text or "unknown"))
                )

            orchestrator_raw = data.get("orchestrator")
            orchestrator = orchestrator_raw if isinstance(orchestrator_raw, Mapping) else {}
            components_raw = orchestrator.get("components")
            jobs_raw = orchestrator.get("jobs")
            enabled_jobs_raw = orchestrator.get("enabled_jobs")

            if isinstance(components_raw, Mapping):
                for name, status_text in sorted(components_raw.items()):
                    orchestrator_components.append(
                        ReadinessDependency(name=str(name), status=str(status_text or "unknown"))
                    )

            if isinstance(jobs_raw, Mapping):
                for name, status_text in sorted(jobs_raw.items()):
                    orchestrator_jobs.append(
                        ReadinessDependency(name=str(name), status=str(status_text or "unknown"))
                    )

            if isinstance(enabled_jobs_raw, Mapping):
                enabled_jobs = {
                    str(name): bool(value)
                    for name, value in sorted(
                        enabled_jobs_raw.items(), key=lambda item: str(item[0])
                    )
                }
            else:
                enabled_jobs = {}

        return ReadinessRecord(
            ok=ok,
            database=database,
            dependencies=tuple(dependencies),
            orchestrator_components=tuple(orchestrator_components),
            orchestrator_jobs=tuple(orchestrator_jobs),
            enabled_jobs=enabled_jobs,
            error_message=error_message,
        )

    @staticmethod
    def _decode_response_payload(response: StarletteResponse) -> Mapping[str, object]:
        body = getattr(response, "body", b"")
        if not body:
            return {}

        charset = response.charset or "utf-8"
        try:
            text = body.decode(charset)
        except (LookupError, UnicodeDecodeError):
            logger.warning(
                "system.ui.readiness.decode_failed",
                extra={"reason": "decode", "charset": charset},
            )
            return {}

        if not text:
            return {}

        try:
            data = loads(text)
        except JSONDecodeError:
            logger.warning(
                "system.ui.readiness.decode_failed",
                extra={"reason": "json"},
            )
            return {}

        if isinstance(data, Mapping):
            return dict(data)

        logger.warning(
            "system.ui.readiness.decode_failed",
            extra={"reason": "type", "type": type(data).__name__},
        )
        return {}

    async def fetch_integrations(self) -> IntegrationSummary:
        try:
            response = await integrations_router.get_integrations(service=self._integration_service)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("system.ui.integrations.error")
            raise AppError(
                "Unable to load integration health.",
                code=ErrorCode.DEPENDENCY_ERROR,
            ) from exc

        if response.data is None:
            return IntegrationSummary(overall="unknown", providers=())

        providers = [
            IntegrationProviderStatus(
                name=provider.name,
                status=provider.status,
                details=dict(provider.details) if provider.details is not None else None,
            )
            for provider in response.data.providers
        ]
        providers.sort(key=lambda item: item.name)
        return IntegrationSummary(overall=response.data.overall, providers=tuple(providers))

    async def validate_secret(
        self,
        request: Request,
        *,
        provider: str,
        override: str | None,
        session_factory: SessionFactory,
    ) -> SecretValidationRecord:
        payload = system_api.SecretValidationRequest(value=override)
        envelope = await system_api.validate_secret(
            provider,
            request,
            payload,
            session_factory=session_factory,
        )
        if not envelope.ok or envelope.data is None:
            logger.warning(
                "system.ui.secret_validation.failed",
                extra={"provider": provider, "ok": envelope.ok},
            )
            raise AppError(
                "Secret validation failed.",
                code=ErrorCode.DEPENDENCY_ERROR,
            )

        validated = envelope.data.validated
        return SecretValidationRecord(
            provider=envelope.data.provider,
            mode=validated.mode,
            valid=validated.valid,
            validated_at=validated.at,
            reason=validated.reason,
            note=validated.note,
        )

    async def fetch_service_badges(self) -> Sequence[ServiceHealthBadge]:
        evaluations = await _load_service_health_evaluations()

        badges = [
            ServiceHealthBadge(
                service=name,
                status=result.status,
                missing=tuple(result.missing),
                optional_missing=tuple(result.optional_missing),
            )
            for name, result in evaluations.items()
        ]
        badges.sort(key=lambda badge: badge.service)
        return tuple(badges)


def get_system_ui_service(
    integration_service: IntegrationService = Depends(get_integration_service),
) -> SystemUiService:
    return SystemUiService(integration_service)


__all__ = [
    "IntegrationProviderStatus",
    "IntegrationSummary",
    "LivenessRecord",
    "ReadinessDependency",
    "ReadinessRecord",
    "SecretValidationRecord",
    "ServiceHealthBadge",
    "SystemUiService",
    "get_system_ui_service",
]
