from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import Request, Response, status
from fastapi.templating import Jinja2Templates

from app.logging import get_logger
from app.ui.assets import asset_url
from app.ui.context import AlertMessage, get_ui_assets
from app.ui.session import UiSession

logger = get_logger("app.ui.router")


templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
templates.env.globals["asset_url"] = asset_url
templates.env.globals["get_ui_assets"] = get_ui_assets


@dataclass(slots=True)
class _LiveFragmentBuilder:
    name: str
    interval: float
    build: Callable[[], Awaitable[dict[str, Any] | None]]


async def _ui_event_stream(
    request: Request, builders: Sequence[_LiveFragmentBuilder]
) -> AsyncGenerator[str, None]:
    if not builders:
        yield ": no-fragments\n\n"
        return

    next_run = {builder.name: 0.0 for builder in builders}
    try:
        while True:
            if await request.is_disconnected():
                break
            now = time.monotonic()
            emitted = False
            for builder in builders:
                target_time = next_run[builder.name]
                if now < target_time:
                    continue
                next_run[builder.name] = now + builder.interval
                try:
                    payload = await builder.build()
                except Exception:  # pragma: no cover - defensive guard
                    logger.exception("ui.events.build_failed", extra={"event": builder.name})
                    continue
                if not payload:
                    continue
                payload.setdefault("event", builder.name)
                data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                yield f"event: fragment\ndata: {data}\n\n"
                emitted = True
            if emitted:
                await asyncio.sleep(0.25)
                continue
            sleep_for = min(max(next_run[name] - now, 0.0) for name in next_run)
            await asyncio.sleep(min(sleep_for, 1.0) if sleep_for > 0 else 0.5)
    except asyncio.CancelledError:  # pragma: no cover - cancellation boundary
        return


def _render_alert_fragment(
    request: Request,
    message: str,
    *,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    retry_url: str | None = None,
    retry_target: str | None = None,
    retry_label_key: str = "fragments.retry",
) -> Response:
    alert = AlertMessage(level="error", text=message or "An unexpected error occurred.")
    context = {
        "request": request,
        "alerts": (alert,),
        "retry_url": retry_url,
        "retry_target": retry_target,
        "retry_label_key": retry_label_key,
    }
    return templates.TemplateResponse(
        request,
        "partials/async_error.j2",
        context,
        status_code=status_code,
    )


def _ensure_csrf_token(request: Request, session: UiSession, manager) -> tuple[str, bool]:
    token = request.cookies.get("csrftoken")
    if token:
        return token, False
    issued = manager.issue(session)
    return issued, True


def _parse_form_body(raw_body: bytes) -> dict[str, str]:
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    parsed = parse_qs(payload)
    return {key: (values[0].strip() if values else "") for key, values in parsed.items()}


__all__ = [
    "logger",
    "templates",
    "_LiveFragmentBuilder",
    "_ui_event_stream",
    "_render_alert_fragment",
    "_ensure_csrf_token",
    "_parse_form_body",
]
