"""Endpoints for Spotify FREE import sessions."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.config import AppConfig
from app.dependencies import get_app_config
from app.db import session_scope
from app.logging import get_logger
from app.models import ImportBatch, ImportSession
from app.utils.spotify_free import (
    InvalidPayloadError,
    TooManyItemsError,
    parse_and_validate_links,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/imports", tags=["Imports"])


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@router.post("/free")
async def create_free_import(
    request: Request,
    config: AppConfig = Depends(get_app_config),
) -> JSONResponse:
    limits = {
        "max_links": config.spotify.free_import_max_playlist_links,
        "max_body_bytes": config.spotify.free_import_max_file_bytes,
    }
    hard_cap_links = (
        config.spotify.free_import_max_playlist_links
        * config.spotify.free_import_hard_cap_multiplier
    )
    hard_cap_bytes = (
        config.spotify.free_import_max_file_bytes * config.spotify.free_import_hard_cap_multiplier
    )

    body = await request.body()
    body_size = len(body)

    if body_size > hard_cap_bytes:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={
                "ok": False,
                "error": {
                    "code": "TOO_MANY_ITEMS",
                    "message": "payload exceeds maximum allowed size",
                },
            },
        )

    content_type = request.headers.get("content-type")

    try:
        parse_result = parse_and_validate_links(
            raw_body=body,
            content_type=content_type,
            max_links=config.spotify.free_import_max_playlist_links,
            hard_cap_links=hard_cap_links,
            allow_user_urls=config.spotify.free_accept_user_urls,
        )
    except TooManyItemsError as exc:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={
                "ok": False,
                "error": {
                    "code": "TOO_MANY_ITEMS",
                    "message": f"received {exc.provided} links which exceeds hard limit {exc.limit}",
                },
            },
        )
    except InvalidPayloadError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"invalid payload: {exc.message}",
                },
            },
        )

    if not parse_result.accepted:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "no valid playlist links in payload",
                },
            },
        )

    session_id = _generate_id("sess")
    batch_records: List[ImportBatch] = []

    for playlist in parse_result.accepted:
        batch_records.append(
            ImportBatch(
                id=_generate_id("batch"),
                session_id=session_id,
                playlist_id=playlist.playlist_id,
            )
        )

    totals_payload: Dict[str, Any] = {
        "provided": parse_result.total_links,
        "accepted": len(parse_result.accepted),
        "rejected": len(parse_result.rejected),
        "skipped": len(parse_result.skipped),
    }

    with session_scope() as db_session:
        db_session.add(
            ImportSession(
                id=session_id,
                mode="FREE",
                totals_json=json.dumps(totals_payload),
            )
        )
        for record in batch_records:
            db_session.add(record)

    logger.info(
        "processed FREE ingest request",
        extra={
            "event": "free_ingest",
            "session_id": session_id,
            "accepted": len(parse_result.accepted),
            "rejected": len(parse_result.rejected),
            "skipped": len(parse_result.skipped),
        },
    )

    response_payload = {
        "ok": True,
        "data": {
            "import_session_id": session_id,
            "accepted_count": len(parse_result.accepted),
            "skipped": list(parse_result.skipped),
            "rejected": [
                {"url": item.url, "reason": item.reason} for item in parse_result.rejected
            ],
            "limits": limits,
        },
        "error": None,
    }

    return JSONResponse(status_code=status.HTTP_200_OK, content=response_payload)
