from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
import secrets
from typing import Final
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request, Response, status

from app.logging import get_logger
from app.logging_events import log_event
from app.ui.session import UiSession, get_session_manager, require_session

logger = get_logger(__name__)

_CSRF_COOKIE: Final[str] = "csrftoken"
_HEADER_NAME: Final[str] = "X-CSRF-Token"
_FORM_FIELD: Final[str] = "csrftoken"


@dataclass(slots=True)
class CsrfManager:
    secret: bytes
    cookies_secure: bool

    def issue(self, session: UiSession) -> str:
        nonce = secrets.token_urlsafe(24)
        payload = f"{session.identifier}:{nonce}".encode()
        signature = hmac.new(self.secret, payload, hashlib.sha256).digest()
        encoded_payload = base64.urlsafe_b64encode(payload).decode()
        encoded_signature = base64.urlsafe_b64encode(signature).decode()
        token = f"{encoded_payload}.{encoded_signature}"
        return token

    def validate(self, session: UiSession, token: str) -> bool:
        payload_b64, sep, signature_b64 = token.partition(".")
        if not sep:
            return False
        try:
            payload = base64.urlsafe_b64decode(payload_b64.encode())
            provided_signature = base64.urlsafe_b64decode(signature_b64.encode())
        except (ValueError, binascii.Error):
            return False
        expected_signature = hmac.new(self.secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(provided_signature, expected_signature):
            return False
        expected_session = f"{session.identifier}:"
        return payload.decode("utf-8").startswith(expected_session)


def build_csrf_manager(secret: str | None, *, cookies_secure: bool = True) -> CsrfManager:
    material = (secret or "").encode("utf-8")
    if not material:
        material = secrets.token_bytes(32)
    derived = hashlib.sha256(material).digest()
    return CsrfManager(secret=derived, cookies_secure=cookies_secure)


def get_csrf_manager(request: Request) -> CsrfManager:
    manager: CsrfManager | None = getattr(request.app.state, "ui_csrf_manager", None)
    session_manager = get_session_manager(request)
    security = session_manager.security
    cookies_secure = security.ui_cookies_secure
    if manager is None or manager.cookies_secure != cookies_secure:
        key_source = ":".join(security.api_keys) if security.api_keys else None
        manager = build_csrf_manager(key_source, cookies_secure=cookies_secure)
        request.app.state.ui_csrf_manager = manager
    return manager


def attach_csrf_cookie(
    response: Response,
    session: UiSession,
    manager: CsrfManager,
    *,
    token: str | None = None,
) -> str:
    issued_token = token or manager.issue(session)
    response.set_cookie(
        _CSRF_COOKIE,
        issued_token,
        httponly=False,
        secure=manager.cookies_secure,
        samesite="lax",
    )
    return issued_token


def clear_csrf_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        _CSRF_COOKIE,
        httponly=False,
        secure=secure,
        samesite="lax",
    )


async def _extract_form_token(request: Request) -> str | None:
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" not in content_type:
        return None
    raw_body = await request.body()
    if not raw_body:
        return None
    try:
        decoded = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    parsed = parse_qs(decoded, keep_blank_values=True)
    values = parsed.get(_FORM_FIELD)
    if not values:
        return None
    token = values[0]
    return token or None


async def enforce_csrf(
    request: Request,
    session: UiSession = Depends(require_session),
    manager: CsrfManager = Depends(get_csrf_manager),
) -> None:
    cookie_token = request.cookies.get(_CSRF_COOKIE)
    candidate_token = request.headers.get(_HEADER_NAME)
    if candidate_token is None:
        candidate_token = await _extract_form_token(request)

    if not candidate_token or not cookie_token:
        log_event(
            logger,
            "ui.csrf",
            component="ui.csrf",
            status="missing",
            path=request.url.path,
            method=request.method,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing CSRF token.",
        )

    if candidate_token != cookie_token or not manager.validate(session, candidate_token):
        log_event(
            logger,
            "ui.csrf",
            component="ui.csrf",
            status="invalid",
            path=request.url.path,
            method=request.method,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token.",
        )


__all__ = [
    "CsrfManager",
    "attach_csrf_cookie",
    "clear_csrf_cookie",
    "enforce_csrf",
    "get_csrf_manager",
]
