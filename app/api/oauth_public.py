from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.dependencies import get_oauth_service
from app.services.oauth_service import (
    OAuthErrorCode,
    OAuthManualRequest,
    OAuthManualResponse,
    OAuthService,
    OAuthSessionStatus,
)

__all__ = ["router_oauth_public"]


router_oauth_public = APIRouter(prefix="/oauth", tags=["OAuth"])


@router_oauth_public.get("/start")
async def oauth_start(
    request: Request, service: OAuthService = Depends(get_oauth_service)
) -> dict[str, Any]:
    try:
        response = service.start(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return {
        "provider": response.provider,
        "authorization_url": response.authorization_url,
        "state": response.state,
        "code_challenge_method": response.code_challenge_method,
        "redirect_uri": response.redirect_uri,
        "expires_at": response.expires_at.isoformat(),
        "manual_completion_available": response.manual_completion_available,
        "manual_completion_url": response.manual_completion_url,
    }


@router_oauth_public.post("/manual")
async def oauth_manual(
    payload: OAuthManualRequest,
    request: Request,
    service: OAuthService = Depends(get_oauth_service),
) -> JSONResponse:
    result: OAuthManualResponse = await service.manual(
        request=payload, client_ip=request.client.host if request.client else None
    )
    status_code = status.HTTP_200_OK if result.ok else status.HTTP_400_BAD_REQUEST
    body = {
        "ok": result.ok,
        "provider": result.provider,
        "state": result.state,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        "error_code": result.error_code.value if result.error_code else None,
        "message": result.message,
    }
    if result.error_code is OAuthErrorCode.OAUTH_MANUAL_RATE_LIMITED:
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    return JSONResponse(status_code=status_code, content=body)


@router_oauth_public.get("/status/{state}")
async def oauth_status(
    state: str, service: OAuthService = Depends(get_oauth_service)
) -> JSONResponse:
    status_response = service.status(state)
    body = {
        "provider": status_response.provider,
        "state": status_response.state,
        "status": status_response.status.value,
        "created_at": status_response.created_at.isoformat(),
        "expires_at": status_response.expires_at.isoformat(),
        "completed_at": status_response.completed_at.isoformat()
        if status_response.completed_at
        else None,
        "manual_completion_available": status_response.manual_completion_available,
        "manual_completion_url": status_response.manual_completion_url,
        "redirect_uri": status_response.redirect_uri,
        "error_code": status_response.error_code.value if status_response.error_code else None,
        "message": status_response.message,
    }
    return JSONResponse(status_code=status.HTTP_200_OK, content=body)


@router_oauth_public.get("/health")
async def oauth_health(service: OAuthService = Depends(get_oauth_service)) -> JSONResponse:
    info = service.health()
    store_info = info.get("store", {}) if isinstance(info, dict) else {}
    body = {
        "provider": info.get("provider", "spotify"),
        "backend": store_info.get("backend", "memory"),
        "active_transactions": info.get("active_transactions", 0),
        "ttl_seconds": info.get("ttl_seconds"),
        "manual_enabled": info.get("manual_enabled"),
        "redirect_uri": info.get("redirect_uri"),
        "public_host_hint": info.get("public_host_hint"),
        "store": store_info,
    }
    return JSONResponse(status_code=status.HTTP_200_OK, content=body)

