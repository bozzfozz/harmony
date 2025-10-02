"""FastAPI dependency providers."""

from __future__ import annotations

from functools import lru_cache
import hmac
from typing import Generator

from fastapi import Depends, Request, status

from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.core.matching_engine import MusicMatchingEngine
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.core.transfers_api import TransfersApi
from app.db import get_session
from app.integrations.provider_gateway import ProviderGateway
from app.integrations.registry import ProviderRegistry
from app.errors import AppError, ErrorCode
from app.logging import get_logger
from app.services.download_service import DownloadService
from app.services.integration_service import IntegrationService
from app.services.watchlist_service import WatchlistService


_integration_service_override: IntegrationService | None = None

logger = get_logger(__name__)


@lru_cache()
def get_app_config() -> AppConfig:
    return load_config()


@lru_cache()
def get_spotify_client() -> SpotifyClient:
    return SpotifyClient(get_app_config().spotify)


@lru_cache()
def get_soulseek_client() -> SoulseekClient:
    return SoulseekClient(get_app_config().soulseek)


@lru_cache()
def get_transfers_api() -> TransfersApi:
    return TransfersApi(get_soulseek_client())


@lru_cache()
def get_provider_registry() -> ProviderRegistry:
    return ProviderRegistry(config=get_app_config())


@lru_cache()
def get_provider_gateway() -> ProviderGateway:
    registry = get_provider_registry()
    registry.initialise()
    providers = registry.track_providers()
    config = registry.gateway_config
    return ProviderGateway(providers=providers, config=config)


@lru_cache()
def get_integration_service() -> IntegrationService:
    if _integration_service_override is not None:
        return _integration_service_override
    return IntegrationService(registry=get_provider_registry())


def set_integration_service_override(service: IntegrationService | None) -> None:
    global _integration_service_override
    _integration_service_override = service
    get_integration_service.cache_clear()


@lru_cache()
def get_matching_engine() -> MusicMatchingEngine:
    return MusicMatchingEngine()


def get_db() -> Generator[Session, None, None]:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_watchlist_service(session: Session = Depends(get_db)) -> WatchlistService:
    return WatchlistService(session=session)


def get_download_service(
    session: Session = Depends(get_db),
    transfers: TransfersApi = Depends(get_transfers_api),
) -> DownloadService:
    return DownloadService(session=session, transfers=transfers)


def _is_allowlisted(path: str, allowlist: tuple[str, ...]) -> bool:
    for prefix in allowlist:
        if not prefix:
            continue
        if prefix == "/" and path == "/":
            return True
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    return False


def _extract_presented_key(request: Request) -> str | None:
    header_key = request.headers.get("X-API-Key")
    if header_key and header_key.strip():
        return header_key.strip()

    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        candidate = auth_header[7:].strip()
        if candidate:
            return candidate
    return None


def require_api_key(request: Request, *, force: bool = False) -> None:
    config = get_app_config()
    security = config.security

    if not force and not security.require_auth:
        return

    if request.method.upper() == "OPTIONS":
        return

    if _is_allowlisted(request.url.path, security.allowlist):
        return

    if not security.api_keys:
        logger.warning(
            "API key authentication enabled but no keys configured",  # pragma: no cover - logging string
            extra={
                "event": "auth.misconfigured",
                "path": request.url.path,
                "method": request.method,
            },
        )
        raise AppError(
            "An API key is required to access this resource.",
            code=ErrorCode.INTERNAL_ERROR,
            http_status=status.HTTP_401_UNAUTHORIZED,
        )

    presented_key = _extract_presented_key(request)
    if not presented_key:
        logger.warning(
            "Missing API key for protected endpoint",  # pragma: no cover - logging string
            extra={
                "event": "auth.unauthorized",
                "path": request.url.path,
                "method": request.method,
            },
        )
        raise AppError(
            "An API key is required to access this resource.",
            code=ErrorCode.INTERNAL_ERROR,
            http_status=status.HTTP_401_UNAUTHORIZED,
        )

    for valid_key in security.api_keys:
        if hmac.compare_digest(presented_key, valid_key):
            return

    logger.warning(
        "Invalid API key rejected",  # pragma: no cover - logging string
        extra={
            "event": "auth.forbidden",
            "path": request.url.path,
            "method": request.method,
        },
    )
    raise AppError(
        "The provided API key is not valid.",
        code=ErrorCode.INTERNAL_ERROR,
        http_status=status.HTTP_403_FORBIDDEN,
    )
