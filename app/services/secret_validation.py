"""Secret validation service supporting live checks with format fallbacks."""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Deque, Dict, Literal, Optional
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import status

from app.config import get_env
from app.errors import DependencyError, RateLimitedError, ValidationAppError
from app.logging import get_logger
from app.services.secret_store import SecretRecord, SecretStore

logger = get_logger(__name__)

ValidationMode = Literal["live", "format"]


@dataclass(slots=True)
class SecretValidationSettings:
    """Configuration for live secret validation."""

    timeout_ms: int
    max_requests_per_minute: int
    slskd_base_url: str

    @classmethod
    def from_env(cls) -> "SecretValidationSettings":
        timeout_ms = _as_int(get_env("SECRET_VALIDATE_TIMEOUT_MS"), default=800)
        max_per_min = _as_int(get_env("SECRET_VALIDATE_MAX_PER_MIN"), default=3)
        base_url = (get_env("SLSKD_BASE_URL") or "").strip() or "http://localhost:5030"
        return cls(
            timeout_ms=max(timeout_ms, 100),
            max_requests_per_minute=max(1, max_per_min),
            slskd_base_url=base_url.rstrip("/") or "http://localhost:5030",
        )


@dataclass(slots=True)
class SecretValidationDetails:
    """Outcome payload returned to API consumers."""

    mode: ValidationMode
    valid: bool
    at: datetime
    reason: Optional[str] = None
    note: Optional[str] = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": self.mode,
            "valid": self.valid,
            "at": self.at,
        }
        if self.reason:
            payload["reason"] = self.reason
        if self.note:
            payload["note"] = self.note
        return payload


@dataclass(slots=True)
class SecretValidationResult:
    provider: str
    validated: SecretValidationDetails

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "validated": self.validated.as_dict(),
        }


ProviderValidator = Callable[[str], tuple[bool, Optional[str]]]


@dataclass(slots=True)
class ProviderDescriptor:
    """Configuration for provider-specific validation behaviour."""

    name: str
    format_validator: ProviderValidator
    live_validator: Callable[
        ["SecretValidationService", str, SecretStore], Awaitable[SecretValidationDetails]
    ]


def _as_int(raw: Optional[str], *, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slskd_format(value: str) -> tuple[bool, Optional[str]]:
    normalized = value.strip()
    if not normalized:
        return False, "secret missing"
    if not 12 <= len(normalized) <= 128:
        return False, "expected length between 12 and 128 characters"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized):
        return False, "unexpected characters"
    return True, None


def _spotify_secret_format(value: str) -> tuple[bool, Optional[str]]:
    normalized = value.strip()
    if not normalized:
        return False, "secret missing"
    if not 6 <= len(normalized) <= 128:
        return False, "expected length between 6 and 128 characters"
    if not re.fullmatch(r"[A-Za-z0-9]{6,128}", normalized):
        return False, "must consist of alphanumeric characters"
    return True, None


class SecretValidationService:
    """Service executing live secret checks with deterministic fallbacks."""

    _PROVIDERS: Dict[str, ProviderDescriptor] = {
        "slskd_api_key": ProviderDescriptor(
            name="slskd_api_key",
            format_validator=_slskd_format,
            live_validator=lambda self, secret, store: self._validate_slskd(secret, store),
        ),
        "spotify_client_secret": ProviderDescriptor(
            name="spotify_client_secret",
            format_validator=_spotify_secret_format,
            live_validator=lambda self, secret, store: self._validate_spotify(secret, store),
        ),
    }

    def __init__(
        self,
        *,
        settings: SecretValidationSettings | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings or SecretValidationSettings.from_env()
        self._client_factory = client_factory or self._default_client_factory
        self._monotonic = monotonic or time.monotonic
        self._request_history: Dict[str, Deque[float]] = {
            provider: deque() for provider in self._PROVIDERS
        }
        self._locks: Dict[str, asyncio.Lock] = {
            provider: asyncio.Lock() for provider in self._PROVIDERS
        }

    async def validate(
        self,
        provider: str,
        *,
        store: SecretStore,
        override: Optional[str] = None,
    ) -> SecretValidationResult:
        descriptor = self._PROVIDERS.get(provider)
        if descriptor is None:
            raise ValidationAppError(f"Unsupported provider '{provider}'")

        if override is not None:
            override_value = override.strip()
            if not override_value:
                raise ValidationAppError("Override value must not be empty.")
            secret_value = override_value
        else:
            secret_record = store.secret_for_provider(provider)
            secret_value = (secret_record.value or "").strip()

        if not secret_value:
            details = SecretValidationDetails(
                mode="format",
                valid=False,
                at=_now(),
                reason="secret not configured",
            )
            logger.info(
                "Secret format invalid",  # pragma: no cover - logging path
                extra={
                    "event": "secret.validate",
                    "provider": provider,
                    "mode": details.mode,
                    "valid": details.valid,
                    "reason": details.reason,
                },
            )
            return SecretValidationResult(provider=provider, validated=details)

        format_valid, format_reason = descriptor.format_validator(secret_value)
        if not format_valid:
            details = SecretValidationDetails(
                mode="format",
                valid=False,
                at=_now(),
                reason=format_reason or "invalid format",
            )
            logger.info(
                "Secret format validation failed",  # pragma: no cover - logging path
                extra={
                    "event": "secret.validate",
                    "provider": provider,
                    "mode": details.mode,
                    "valid": details.valid,
                    "reason": details.reason,
                },
            )
            return SecretValidationResult(provider=provider, validated=details)

        await self._enforce_rate_limit(provider)

        start = self._monotonic()
        try:
            details = await descriptor.live_validator(self, secret_value, store)
        except httpx.TimeoutException:
            details = SecretValidationDetails(
                mode="format",
                valid=True,
                at=_now(),
                note="upstream unreachable",
            )
        except httpx.RequestError:
            details = SecretValidationDetails(
                mode="format",
                valid=True,
                at=_now(),
                note="upstream unreachable",
            )
        duration_ms = (self._monotonic() - start) * 1000
        logger.info(
            "Secret validation completed",  # pragma: no cover - logging path
            extra={
                "event": "secret.validate",
                "provider": provider,
                "mode": details.mode,
                "valid": details.valid,
                "note": details.note,
                "reason": details.reason,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return SecretValidationResult(provider=provider, validated=details)

    async def _enforce_rate_limit(self, provider: str) -> None:
        history = self._request_history[provider]
        limit = self._settings.max_requests_per_minute
        window_seconds = 60.0
        now = self._monotonic()
        async with self._locks[provider]:
            while history and now - history[0] > window_seconds:
                history.popleft()
            if len(history) >= limit:
                retry_after_ms = int(max(0.0, window_seconds - (now - history[0])) * 1000)
                raise RateLimitedError(
                    "Too many validation attempts.",
                    retry_after_ms=retry_after_ms,
                )
            history.append(now)

    def _default_client_factory(self) -> httpx.AsyncClient:
        timeout_seconds = max(0.1, self._settings.timeout_ms / 1000.0)
        return httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)

    async def _request_slskd(self, api_key: str, base_url: str) -> httpx.Response:
        parsed = urlparse(base_url.strip())
        base_segments = [segment for segment in parsed.path.split("/") if segment]
        target_segments = ["api", "v2", "me"]
        overlap = 0
        max_overlap = min(len(base_segments), len(target_segments))
        for size in range(max_overlap, 0, -1):
            if base_segments[-size:] == target_segments[:size]:
                overlap = size
                break
        combined_segments = base_segments + target_segments[overlap:]
        path = "/" + "/".join(combined_segments)
        normalized_url = urlunparse(parsed._replace(path=path, params="", query="", fragment=""))
        async with self._client_factory() as client:
            return await client.get(normalized_url, headers={"X-API-Key": api_key})

    async def _request_spotify(self, client_id: str, client_secret: str) -> httpx.Response:
        data = {"grant_type": "client_credentials"}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with self._client_factory() as client:
            return await client.post(
                "https://accounts.spotify.com/api/token",
                data=data,
                headers=headers,
                auth=(client_id, client_secret),
            )

    async def _validate_slskd(
        self, secret_value: str, store: SecretStore
    ) -> SecretValidationDetails:
        base_url = (store.get("SLSKD_URL").value or "").strip() or self._settings.slskd_base_url
        response = await self._request_slskd(secret_value, base_url)
        if 200 <= response.status_code < 300:
            return SecretValidationDetails(mode="live", valid=True, at=_now())
        if response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
            return SecretValidationDetails(
                mode="live",
                valid=False,
                at=_now(),
                reason="invalid credentials",
            )
        if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise DependencyError(
                "validation failed: upstream",
                status_code=status.HTTP_424_FAILED_DEPENDENCY,
                meta={"status": response.status_code},
            )
        if response.status_code >= 500:
            raise DependencyError(
                "validation failed: upstream",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                meta={"status": response.status_code},
            )
        return SecretValidationDetails(
            mode="live",
            valid=False,
            at=_now(),
            reason=f"unexpected status {response.status_code}",
        )

    async def _validate_spotify(
        self, secret_value: str, store: SecretStore
    ) -> SecretValidationDetails:
        client_id_record: SecretRecord = store.dependent_setting("spotify_client_secret", index=1)
        client_id = (client_id_record.value or "").strip()
        if not client_id:
            return SecretValidationDetails(
                mode="format",
                valid=False,
                at=_now(),
                reason="spotify client id missing",
            )
        response = await self._request_spotify(client_id, secret_value)
        if response.status_code == status.HTTP_200_OK:
            return SecretValidationDetails(mode="live", valid=True, at=_now())
        if response.status_code in {status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED}:
            return SecretValidationDetails(
                mode="live",
                valid=False,
                at=_now(),
                reason="invalid credentials",
            )
        if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise DependencyError(
                "validation failed: upstream",
                status_code=status.HTTP_424_FAILED_DEPENDENCY,
                meta={"status": response.status_code},
            )
        if response.status_code >= 500:
            raise DependencyError(
                "validation failed: upstream",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                meta={"status": response.status_code},
            )
        return SecretValidationDetails(
            mode="live",
            valid=False,
            at=_now(),
            reason=f"unexpected status {response.status_code}",
        )
