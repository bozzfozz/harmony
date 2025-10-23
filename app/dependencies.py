"""FastAPI dependency providers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Generator
from functools import lru_cache
import hmac
from threading import Lock
from typing import TYPE_CHECKING, Any

from fastapi import Depends, Request, status
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.core.matching_engine import MusicMatchingEngine
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.core.transfers_api import TransfersApi
from app.db import SessionCallable, get_session, run_session
from app.errors import AuthenticationRequiredError
from app.integrations.provider_gateway import ProviderGateway
from app.integrations.registry import ProviderRegistry
from app.logging import get_logger
from app.oauth import get_oauth_store, startup_check_oauth_store
from app.oauth.transactions import OAuthTransactionStore
from app.services.artist_service import ArtistService
from app.services.download_service import DownloadService
from app.services.integration_service import IntegrationService
from app.services.oauth_service import ManualRateLimiter, OAuthService
from app.services.watchlist_service import WatchlistService

_integration_service_override: IntegrationService | None = None
_oauth_service_instance: OAuthService | None = None
_oauth_store_instance: OAuthTransactionStore | None = None
_oauth_store_checked = False
_oauth_store_lock = Lock()
_oauth_service_lock = Lock()

logger = get_logger(__name__)


@lru_cache
def get_app_config() -> AppConfig:
    return load_config()


def get_oauth_service(request: Request) -> OAuthService:
    service = getattr(request.app.state, "oauth_service", None)
    if isinstance(service, OAuthService):
        return service
    global _oauth_service_instance
    with _oauth_service_lock:
        if _oauth_service_instance is None:
            config = get_app_config()
            store = _ensure_oauth_store(config)
            manual_limit = ManualRateLimiter(limit=6, window_seconds=300.0)
            _oauth_service_instance = OAuthService(
                config=config,
                transactions=store,
                manual_limit=manual_limit,
            )
        service = _oauth_service_instance
    request.app.state.oauth_transaction_store = _ensure_oauth_store(get_app_config())
    request.app.state.oauth_service = service
    return service


def set_oauth_service_instance(service: OAuthService | None) -> None:
    global _oauth_service_instance
    with _oauth_service_lock:
        _oauth_service_instance = service


def _ensure_oauth_store(config: AppConfig) -> OAuthTransactionStore:
    global _oauth_store_instance, _oauth_store_checked
    with _oauth_store_lock:
        if _oauth_store_instance is None:
            store = get_oauth_store(config)
            if not _oauth_store_checked:
                startup_check_oauth_store(store, split_mode=config.oauth.split_mode)
                _oauth_store_checked = True
            _oauth_store_instance = store
        return _oauth_store_instance


def set_oauth_store_instance(store: OAuthTransactionStore | None) -> None:
    global _oauth_store_instance, _oauth_store_checked
    with _oauth_store_lock:
        _oauth_store_instance = store
        _oauth_store_checked = store is not None


@lru_cache
def get_spotify_client() -> SpotifyClient | None:
    config = get_app_config().spotify
    credentials = (
        config.client_id,
        config.client_secret,
        config.redirect_uri,
    )
    for value in credentials:
        if not isinstance(value, str) or not value.strip():
            logger.info(
                "Spotify client is disabled due to missing credentials",
                extra={"event": "spotify.client_disabled"},
            )
            return None
    try:
        return SpotifyClient(config)
    except ValueError:
        logger.warning(
            "Spotify client initialisation failed due to incomplete credentials",
            extra={"event": "spotify.client_invalid_config"},
        )
        return None


@lru_cache
def get_soulseek_client() -> SoulseekClient:
    return SoulseekClient(get_app_config().soulseek)


@lru_cache
def get_transfers_api() -> TransfersApi:
    return TransfersApi(get_soulseek_client())


@lru_cache
def get_provider_registry() -> ProviderRegistry:
    return ProviderRegistry(config=get_app_config())


@lru_cache
def get_provider_gateway() -> ProviderGateway:
    registry = get_provider_registry()
    registry.initialise()
    providers = registry.track_providers()
    config = registry.gateway_config
    return ProviderGateway(providers=providers, config=config)


@lru_cache
def get_integration_service() -> IntegrationService:
    if _integration_service_override is not None:
        return _integration_service_override
    return IntegrationService(registry=get_provider_registry())


def set_integration_service_override(service: IntegrationService | None) -> None:
    global _integration_service_override
    _integration_service_override = service
    get_integration_service.cache_clear()


@lru_cache
def get_matching_engine() -> MusicMatchingEngine:
    return MusicMatchingEngine()


def get_db() -> Generator[Session, None, None]:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


SessionRunner = Callable[[SessionCallable[Any]], Awaitable[Any]]


def get_session_runner() -> SessionRunner:
    async def runner(func: SessionCallable[Any]) -> Any:
        return await run_session(func)

    return runner


if TYPE_CHECKING:  # pragma: no cover - import hints only for static analysis
    from app.hdm.orchestrator import HdmOrchestrator
    from app.hdm.runtime import HdmRuntime


def get_hdm_runtime(request: Request) -> HdmRuntime:
    from app.hdm.runtime import HdmRuntime

    runtime = getattr(request.app.state, "hdm_runtime", None)
    if not isinstance(runtime, HdmRuntime):
        raise RuntimeError("Harmony Download Manager runtime is not available")
    return runtime


def get_hdm_orchestrator(request: Request) -> HdmOrchestrator:
    runtime = get_hdm_runtime(request)
    return runtime.orchestrator


@lru_cache
def get_watchlist_service() -> WatchlistService:
    return WatchlistService()


@lru_cache
def get_artist_service() -> ArtistService:
    return ArtistService()


def get_download_service(
    session: Session = Depends(get_db),
    session_runner: SessionRunner = Depends(get_session_runner),
    transfers: TransfersApi = Depends(get_transfers_api),
) -> DownloadService:
    return DownloadService(
        session=session,
        session_runner=session_runner,
        transfers=transfers,
    )


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
            (
                "API key authentication enabled but no keys configured"
            ),  # pragma: no cover - logging string
            extra={
                "event": "auth.misconfigured",
                "path": request.url.path,
                "method": request.method,
            },
        )
        raise AuthenticationRequiredError(
            "An API key is required to access this resource.",
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
        raise AuthenticationRequiredError(
            "An API key is required to access this resource.",
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
    raise AuthenticationRequiredError(
        "The provided API key is not valid.",
        status_code=status.HTTP_403_FORBIDDEN,
    )
