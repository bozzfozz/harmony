"""Integration diagnostics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.dependencies import get_integration_service
from app.errors import InternalServerError
from app.integrations.health import IntegrationHealth
from app.services.integration_service import IntegrationService


class ProviderInfo(BaseModel):
    name: str
    status: str
    details: dict[str, object] | None = None


class IntegrationsData(BaseModel):
    overall: str
    providers: list[ProviderInfo]


class IntegrationsResponse(BaseModel):
    ok: bool
    data: IntegrationsData | None = None
    error: dict | None = None


router = APIRouter(tags=["Integrations"])


@router.get(
    "/integrations", response_model=IntegrationsResponse, status_code=status.HTTP_200_OK
)
async def get_integrations(
    service: IntegrationService = Depends(get_integration_service),
) -> IntegrationsResponse:
    try:
        report: IntegrationHealth = await service.health()
    except Exception as exc:  # pragma: no cover - defensive guard
        raise InternalServerError("Failed to retrieve integration status.") from exc
    providers = [
        ProviderInfo(name=item.provider, status=item.status, details=dict(item.details))
        for item in report.providers
    ]
    return IntegrationsResponse(
        ok=True, data=IntegrationsData(overall=report.overall, providers=providers)
    )
