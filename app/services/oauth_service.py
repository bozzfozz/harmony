"""Service layer handling Spotify OAuth flows including manual callbacks."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Lock
from typing import Any, Callable, Mapping
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import Request
from pydantic import BaseModel, Field

from app.config import AppConfig
from app.core.spotify_cache import SettingsCacheHandler
from app.logging import get_logger
from app.oauth.transactions import (
    OAuthTransactionStore,
    Transaction,
    TransactionExpiredError,
    TransactionNotFoundError,
    TransactionUsedError,
)

__all__ = [
    "OAuthErrorCode",
    "OAuthManualRequest",
    "OAuthManualResponse",
    "OAuthService",
    "OAuthStartResponse",
    "OAuthStatusResponse",
    "OAuthSessionStatus",
]

logger = get_logger(__name__)


class OAuthErrorCode(str, Enum):
    OAUTH_STATE_MISMATCH = "OAUTH_STATE_MISMATCH"
    OAUTH_CODE_EXPIRED = "OAUTH_CODE_EXPIRED"
    OAUTH_INVALID_REDIRECT = "OAUTH_INVALID_REDIRECT"
    OAUTH_TOKEN_EXCHANGE_FAILED = "OAUTH_TOKEN_EXCHANGE_FAILED"
    OAUTH_MANUAL_RATE_LIMITED = "OAUTH_MANUAL_RATE_LIMITED"


@dataclass(slots=True)
class OAuthStartResponse:
    provider: str
    authorization_url: str
    state: str
    code_challenge_method: str
    expires_at: datetime
    redirect_uri: str
    manual_completion_available: bool
    manual_completion_url: str | None


class OAuthManualRequest(BaseModel):
    redirect_url: str = Field(..., min_length=1)


@dataclass(slots=True)
class OAuthManualResponse:
    ok: bool
    provider: str
    state: str | None
    completed_at: datetime | None
    error_code: OAuthErrorCode | None = None
    message: str | None = None


class OAuthSessionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class OAuthStatusResponse:
    provider: str
    state: str
    status: OAuthSessionStatus
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None
    manual_completion_available: bool
    manual_completion_url: str | None
    redirect_uri: str
    error_code: OAuthErrorCode | None = None
    message: str | None = None


class ManualRateLimiter:
    def __init__(self, *, limit: int, window_seconds: float) -> None:
        self._limit = max(1, limit)
        self._window = max(1.0, window_seconds)
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str) -> None:
        now = time.monotonic()
        entries = self._hits.setdefault(key, [])
        entries[:] = [timestamp for timestamp in entries if now - timestamp <= self._window]
        if len(entries) >= self._limit:
            raise RuntimeError("rate limited")
        entries.append(now)


class OAuthService:
    def __init__(
        self,
        *,
        config: AppConfig,
        transactions: OAuthTransactionStore,
        http_timeout: float = 10.0,
        manual_limit: ManualRateLimiter | None = None,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._config = config
        self._transactions = transactions
        self._http_timeout = max(1.0, http_timeout)
        self._cache_handler = SettingsCacheHandler()
        self._manual_limit = manual_limit or ManualRateLimiter(limit=6, window_seconds=300.0)
        self._http_client_factory = http_client_factory
        self._status_lock = Lock()
        self._statuses: dict[str, OAuthStatusResponse] = {}

    @property
    def redirect_uri(self) -> str:
        return self._config.oauth.redirect_uri

    @property
    def manual_enabled(self) -> bool:
        return self._config.oauth.manual_callback_enabled

    @property
    def public_host_hint(self) -> str | None:
        hint = (self._config.oauth.public_host_hint or "").strip()
        return hint or None

    def _manual_completion_url(self) -> str | None:
        if not self.manual_enabled:
            return None
        base = (self._config.oauth.public_base or "").rstrip("/")
        if not base:
            return "/manual"
        return f"{base}/manual"

    def _generate_state(self) -> str:
        return secrets.token_urlsafe(24)

    def _generate_code_verifier(self) -> str:
        verifier = secrets.token_urlsafe(64)
        if len(verifier) < 43:
            verifier = (verifier + secrets.token_urlsafe(64))[:64]
        return verifier[:128]

    def _build_code_challenge(self, verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("utf-8")).digest()
        encoded = base64.urlsafe_b64encode(digest).decode("ascii")
        return encoded.rstrip("=")

    def _transaction_ttl(self) -> timedelta:
        return self._transactions.ttl

    def _state_fingerprint(self, state: str) -> str:
        digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
        return digest[:12]

    def _record_pending_status(self, *, state: str, created_at: datetime) -> None:
        manual_url = self._manual_completion_url()
        record = OAuthStatusResponse(
            provider="spotify",
            state=state,
            status=OAuthSessionStatus.PENDING,
            created_at=created_at,
            expires_at=created_at + self._transaction_ttl(),
            completed_at=None,
            manual_completion_available=self.manual_enabled,
            manual_completion_url=manual_url,
            redirect_uri=self.redirect_uri,
            error_code=None,
            message=None,
        )
        with self._status_lock:
            self._statuses[state] = record

    def _update_status_record(
        self,
        state: str,
        *,
        status: OAuthSessionStatus,
        message: str | None = None,
        error_code: OAuthErrorCode | None = None,
        completed_at: datetime | None = None,
        reference: datetime | None = None,
    ) -> None:
        now = reference or datetime.now(timezone.utc)
        manual_url = self._manual_completion_url()
        with self._status_lock:
            record = self._statuses.get(state)
            if record is None:
                record = OAuthStatusResponse(
                    provider="spotify",
                    state=state,
                    status=status,
                    created_at=now,
                    expires_at=now + self._transaction_ttl(),
                    completed_at=completed_at,
                    manual_completion_available=self.manual_enabled,
                    manual_completion_url=manual_url,
                    redirect_uri=self.redirect_uri,
                    error_code=error_code,
                    message=message,
                )
            else:
                record.status = status
                record.completed_at = completed_at
                record.error_code = error_code
                record.message = message
                record.manual_completion_available = self.manual_enabled
                record.manual_completion_url = manual_url
                record.redirect_uri = self.redirect_uri
                if reference is not None and status is OAuthSessionStatus.PENDING:
                    record.created_at = reference
                    record.expires_at = reference + self._transaction_ttl()
                else:
                    record.expires_at = record.created_at + self._transaction_ttl()
            self._statuses[state] = record

    def _purge_statuses(self, reference: datetime) -> None:
        ttl = self._transaction_ttl()
        cutoff = reference - (ttl * 2)
        stale = [state for state, record in self._statuses.items() if record.created_at <= cutoff]
        for state in stale:
            self._statuses.pop(state, None)

    def status(self, state: str) -> OAuthStatusResponse:
        now = datetime.now(timezone.utc)
        manual_url = self._manual_completion_url()
        with self._status_lock:
            self._purge_statuses(now)
            record = self._statuses.get(state)
            if record is None:
                return OAuthStatusResponse(
                    provider="spotify",
                    state=state,
                    status=OAuthSessionStatus.UNKNOWN,
                    created_at=now,
                    expires_at=now,
                    completed_at=None,
                    manual_completion_available=self.manual_enabled,
                    manual_completion_url=manual_url,
                    redirect_uri=self.redirect_uri,
                    error_code=None,
                    message="State is unknown or expired.",
                )
            if record.status is OAuthSessionStatus.PENDING and record.expires_at <= now:
                record.status = OAuthSessionStatus.EXPIRED
                record.error_code = OAuthErrorCode.OAUTH_CODE_EXPIRED
                record.message = "Authorization code expired. Start a new session."
                record.completed_at = None
            record.manual_completion_available = self.manual_enabled
            record.manual_completion_url = manual_url
            record.redirect_uri = self.redirect_uri
            return replace(record)

    def _authorization_url(self, *, state: str, code_challenge: str) -> str:
        params = {
            "client_id": self._config.spotify.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": self._config.spotify.scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        base = "https://accounts.spotify.com/authorize"
        return f"{base}?{urlencode(params)}"

    def start(self, request: Request) -> OAuthStartResponse:
        if not self._config.spotify.client_id or not self._config.spotify.client_secret:
            raise ValueError("Spotify credentials missing; OAuth disabled")
        state = self._generate_state()
        verifier = self._generate_code_verifier()
        challenge = self._build_code_challenge(verifier)
        issued_at = datetime.now(timezone.utc)
        ttl_seconds = int(self._transaction_ttl().total_seconds())
        meta = {
            "provider": "spotify",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "redirect_uri": self.redirect_uri,
            "client_hint_ip": request.client.host if request.client else None,
        }
        self._transactions.create(
            state=state,
            code_verifier=verifier,
            meta=meta,
            ttl_seconds=ttl_seconds,
        )
        expires_at = issued_at + self._transaction_ttl()
        manual_url = self._manual_completion_url()
        self._record_pending_status(state=state, created_at=issued_at)
        logger.info(
            "OAuth transaction created",
            extra={
                "event": "oauth.transaction.created",
                "provider": "spotify",
                "state_fingerprint": self._state_fingerprint(state),
                "client_hint_ip": meta.get("client_hint_ip"),
            },
        )
        return OAuthStartResponse(
            provider="spotify",
            authorization_url=self._authorization_url(state=state, code_challenge=challenge),
            state=state,
            code_challenge_method="S256",
            expires_at=expires_at,
            redirect_uri=self.redirect_uri,
            manual_completion_available=self.manual_enabled,
            manual_completion_url=manual_url,
        )

    def _build_http_client(self) -> httpx.AsyncClient:
        if self._http_client_factory is not None:
            return self._http_client_factory()
        return httpx.AsyncClient(timeout=self._http_timeout)

    async def _exchange_code(self, code: str, transaction: Transaction) -> Mapping[str, Any]:
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": str(transaction.meta.get("redirect_uri", self.redirect_uri)),
            "client_id": self._config.spotify.client_id,
            "code_verifier": transaction.code_verifier,
        }
        if self._config.spotify.client_secret:
            payload["client_secret"] = self._config.spotify.client_secret
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with self._build_http_client() as client:
            response = await client.post(
                "https://accounts.spotify.com/api/token",
                data=payload,
                headers=headers,
            )
        if response.status_code >= 400:
            logger.error(
                "Spotify token exchange failed",
                extra={
                    "event": "oauth.token_exchange.failed",
                    "provider": transaction.meta.get("provider", "spotify"),
                    "status": response.status_code,
                },
            )
            raise RuntimeError("token exchange failed")
        data = response.json()
        if not isinstance(data, Mapping):
            raise RuntimeError("unexpected token response")
        token_info = dict(data)
        expires_in = int(token_info.get("expires_in") or 0)
        token_info["expires_at"] = int(time.time()) + max(0, expires_in)
        token_info.setdefault("scope", self._config.spotify.scope)
        self._cache_handler.save_token_to_cache(token_info)
        logger.info(
            "Spotify tokens stored",
            extra={
                "event": "oauth.token_exchange.completed",
                "provider": transaction.meta.get("provider", "spotify"),
                "state_fingerprint": self._state_fingerprint(transaction.state),
            },
        )
        return token_info

    def _consume_transaction(self, state: str) -> Transaction:
        try:
            transaction = self._transactions.consume(state)
        except TransactionNotFoundError:
            logger.warning(
                "OAuth transaction missing or expired",
                extra={
                    "event": "oauth.transaction.missing",
                    "state_fingerprint": self._state_fingerprint(state),
                },
            )
            raise
        except TransactionUsedError:
            logger.warning(
                "OAuth transaction already consumed",
                extra={
                    "event": "oauth.transaction.used",
                    "state_fingerprint": self._state_fingerprint(state),
                },
            )
            raise
        except TransactionExpiredError:
            logger.warning(
                "OAuth transaction expired on consume",
                extra={
                    "event": "oauth.transaction.expired",
                    "state_fingerprint": self._state_fingerprint(state),
                },
            )
            raise
        return transaction

    async def complete(self, *, state: str, code: str) -> Mapping[str, Any]:
        try:
            transaction = self._consume_transaction(state)
        except TransactionNotFoundError:
            self._update_status_record(
                state,
                status=OAuthSessionStatus.FAILED,
                error_code=OAuthErrorCode.OAUTH_STATE_MISMATCH,
                message="State is unknown or already used.",
                completed_at=None,
            )
            raise
        except TransactionUsedError:
            self._update_status_record(
                state,
                status=OAuthSessionStatus.FAILED,
                error_code=OAuthErrorCode.OAUTH_STATE_MISMATCH,
                message="State has already been used.",
                completed_at=None,
            )
            raise
        except TransactionExpiredError:
            logger.warning(
                "OAuth transaction expired",
                extra={
                    "event": "oauth.transaction.expired",
                    "state_fingerprint": self._state_fingerprint(state),
                },
            )
            self._update_status_record(
                state,
                status=OAuthSessionStatus.EXPIRED,
                error_code=OAuthErrorCode.OAUTH_CODE_EXPIRED,
                message="Authorization code expired. Start a new session.",
                completed_at=None,
            )
            raise ValueError(OAuthErrorCode.OAUTH_CODE_EXPIRED.value)
        if transaction.is_expired(reference=datetime.now(timezone.utc)):
            logger.warning(
                "OAuth transaction expired",
                extra={
                    "event": "oauth.transaction.expired",
                    "state_fingerprint": self._state_fingerprint(state),
                },
            )
            self._update_status_record(
                state,
                status=OAuthSessionStatus.EXPIRED,
                error_code=OAuthErrorCode.OAUTH_CODE_EXPIRED,
                message="Authorization code expired. Start a new session.",
                completed_at=None,
            )
            raise ValueError(OAuthErrorCode.OAUTH_CODE_EXPIRED.value)
        try:
            token_info = await self._exchange_code(code, transaction)
        except Exception:
            self._update_status_record(
                state,
                status=OAuthSessionStatus.FAILED,
                error_code=OAuthErrorCode.OAUTH_TOKEN_EXCHANGE_FAILED,
                message="Failed to exchange authorization code.",
                completed_at=None,
            )
            raise
        completed_at = datetime.now(timezone.utc)
        self._update_status_record(
            state,
            status=OAuthSessionStatus.COMPLETED,
            completed_at=completed_at,
            message="Authorization completed successfully.",
        )
        return token_info

    async def manual(
        self, *, request: OAuthManualRequest, client_ip: str | None
    ) -> OAuthManualResponse:
        if not self.manual_enabled:
            return OAuthManualResponse(
                ok=False,
                provider="spotify",
                state=None,
                completed_at=None,
                error_code=OAuthErrorCode.OAUTH_INVALID_REDIRECT,
                message="Manual completion is disabled.",
            )
        key = client_ip or "unknown"
        try:
            self._manual_limit.check(key)
        except RuntimeError:
            return OAuthManualResponse(
                ok=False,
                provider="spotify",
                state=None,
                completed_at=None,
                error_code=OAuthErrorCode.OAUTH_MANUAL_RATE_LIMITED,
                message="Too many attempts. Please try again later.",
            )
        redirect_url = request.redirect_url.strip()
        parsed = urlparse(redirect_url)
        if not parsed.query:
            return OAuthManualResponse(
                ok=False,
                provider="spotify",
                state=None,
                completed_at=None,
                error_code=OAuthErrorCode.OAUTH_INVALID_REDIRECT,
                message="Redirect URL is missing parameters.",
            )
        query = httpx.QueryParams(parsed.query)
        code = query.get("code")
        state = query.get("state")
        if not code or not state:
            if state:
                self._update_status_record(
                    state,
                    status=OAuthSessionStatus.FAILED,
                    error_code=OAuthErrorCode.OAUTH_INVALID_REDIRECT,
                    message="Redirect URL must include code and state.",
                    completed_at=None,
                )
            return OAuthManualResponse(
                ok=False,
                provider="spotify",
                state=state,
                completed_at=None,
                error_code=OAuthErrorCode.OAUTH_INVALID_REDIRECT,
                message="Redirect URL must include code and state.",
            )
        try:
            await self.complete(state=state, code=code)
        except (TransactionNotFoundError, TransactionUsedError):
            return OAuthManualResponse(
                ok=False,
                provider="spotify",
                state=state,
                completed_at=None,
                error_code=OAuthErrorCode.OAUTH_STATE_MISMATCH,
                message="State is unknown or already used.",
            )
        except ValueError as exc:
            if exc.args and exc.args[0] == OAuthErrorCode.OAUTH_CODE_EXPIRED.value:
                return OAuthManualResponse(
                    ok=False,
                    provider="spotify",
                    state=state,
                    completed_at=None,
                    error_code=OAuthErrorCode.OAUTH_CODE_EXPIRED,
                    message="Authorization code expired. Start a new session.",
                )
            return OAuthManualResponse(
                ok=False,
                provider="spotify",
                state=state,
                completed_at=None,
                error_code=OAuthErrorCode.OAUTH_TOKEN_EXCHANGE_FAILED,
                message="Failed to exchange authorization code.",
            )
        except Exception:
            logger.exception(
                "Manual OAuth completion failed",
                extra={
                    "event": "oauth.manual.failed",
                    "state_fingerprint": self._state_fingerprint(state),
                },
            )
            return OAuthManualResponse(
                ok=False,
                provider="spotify",
                state=state,
                completed_at=None,
                error_code=OAuthErrorCode.OAUTH_TOKEN_EXCHANGE_FAILED,
                message="Unexpected error during token exchange.",
            )
        return OAuthManualResponse(
            ok=True,
            provider="spotify",
            state=state,
            completed_at=datetime.now(timezone.utc),
            error_code=None,
            message="Authorization completed successfully.",
        )

    def health(self) -> Mapping[str, Any]:
        describe = getattr(self._transactions, "describe", None)
        store_info: Mapping[str, Any]
        if callable(describe):
            try:
                store_info = describe()
            except Exception:  # pragma: no cover - defensive
                store_info = {"backend": "unknown"}
        else:
            store_info = {
                "backend": "memory",
                "ttl_seconds": int(self._transaction_ttl().total_seconds()),
            }
        return {
            "provider": "spotify",
            "active_transactions": self._transactions.count(),
            "ttl_seconds": int(self._transaction_ttl().total_seconds()),
            "manual_enabled": self.manual_enabled,
            "redirect_uri": self.redirect_uri,
            "public_host_hint": self.public_host_hint,
            "store": store_info,
        }

    def help_page_context(self) -> Mapping[str, Any]:
        manual_url = self._manual_completion_url()
        return {
            "redirect_uri": self.redirect_uri,
            "public_host_hint": self.public_host_hint,
            "manual_url": manual_url,
        }
