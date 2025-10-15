from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Final

from fastapi import Depends, HTTPException, Request, Response, status

from app.logging import get_logger
from app.logging_events import log_event
from app.ui.session import UiSession, get_session_manager, require_session

logger = get_logger(__name__)

_CSRF_COOKIE: Final[str] = "csrftoken"
_HEADER_NAME: Final[str] = "X-CSRF-Token"


@dataclass(slots=True)
class CsrfManager:
    secret: bytes

    def issue(self, session: UiSession) -> str:
        nonce = secrets.token_urlsafe(24)
        payload = f"{session.identifier}:{nonce}".encode("utf-8")
        signature = hmac.new(self.secret, payload, hashlib.sha256).digest()
        token = f"{base64.urlsafe_b64encode(payload).decode()}.{base64.urlsafe_b64encode(signature).decode()}"
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


def build_csrf_manager(secret: str | None) -> CsrfManager:
    material = (secret or "").encode("utf-8")
    if not material:
        material = secrets.token_bytes(32)
    derived = hashlib.sha256(material).digest()
    return CsrfManager(secret=derived)


def get_csrf_manager(request: Request) -> CsrfManager:
    manager: CsrfManager | None = getattr(request.app.state, "ui_csrf_manager", None)
    if manager is None:
        security = get_session_manager(request).security
        key_source = ":".join(security.api_keys) if security.api_keys else None
        manager = build_csrf_manager(key_source)
        request.app.state.ui_csrf_manager = manager
    return manager


def attach_csrf_cookie(response: Response, session: UiSession, manager: CsrfManager) -> str:
    token = manager.issue(session)
    response.set_cookie(
        _CSRF_COOKIE,
        token,
        httponly=False,
        secure=True,
        samesite="lax",
    )
    return token


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(
        _CSRF_COOKIE,
        httponly=False,
        secure=True,
        samesite="lax",
    )


def enforce_csrf(
    request: Request,
    session: UiSession = Depends(require_session),
    manager: CsrfManager = Depends(get_csrf_manager),
) -> None:
    header_token = request.headers.get(_HEADER_NAME)
    cookie_token = request.cookies.get(_CSRF_COOKIE)
    if not header_token or not cookie_token:
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
    if header_token != cookie_token or not manager.validate(session, header_token):
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
