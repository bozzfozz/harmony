"""Integration diagnostics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.dependencies import get_integration_service
from app.errors import InternalServerError
from app.services.integration_service import IntegrationService, ProviderHealth


class ProviderInfo(BaseModel):
    name: str
    enabled: bool
    health: str


class IntegrationsData(BaseModel):
    providers: list[ProviderInfo]


class IntegrationsResponse(BaseModel):
    ok: bool
    data: IntegrationsData | None = None
    error: dict | None = None


router = APIRouter(tags=["Integrations"])


@router.get("/integrations", response_model=IntegrationsResponse, status_code=status.HTTP_200_OK)
def get_integrations(
    service: IntegrationService = Depends(get_integration_service),
) -> IntegrationsResponse:
    try:
        health: list[ProviderHealth] = service.health()
    except Exception as exc:  # pragma: no cover - defensive guard
        raise InternalServerError("Failed to retrieve integration status.") from exc
    providers = [
        ProviderInfo(name=item.name, enabled=item.enabled, health=item.health) for item in health
    ]
    return IntegrationsResponse(ok=True, data=IntegrationsData(providers=providers))
