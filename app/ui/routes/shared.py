from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Literal
from urllib.parse import parse_qs

from fastapi import Request, Response, status
from fastapi.templating import Jinja2Templates

from app.config import AppConfig
from app.logging import get_logger
from app.ui.assets import asset_url
from app.ui.context.base import AlertMessage, get_ui_assets
from app.ui.session import UiSession

logger = get_logger("app.ui.router")


templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
templates.env.globals["asset_url"] = asset_url
templates.env.globals["get_ui_assets"] = get_ui_assets


_LIVE_UPDATES_POLLING: Literal["polling"] = "polling"
_LIVE_UPDATES_SSE: Literal["sse"] = "sse"


def _resolve_live_updates_mode(config: AppConfig) -> Literal["polling", "sse"]:
    ui_config = getattr(config, "ui", None)
    if ui_config is None:
        return _LIVE_UPDATES_POLLING
    mode = getattr(ui_config, "live_updates", _LIVE_UPDATES_POLLING)
    if mode == _LIVE_UPDATES_SSE:
        return _LIVE_UPDATES_SSE
    return _LIVE_UPDATES_POLLING


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


def _extract_download_refresh_params(
    request: Request, values: Mapping[str, str]
) -> tuple[int, int, bool]:
    def _parse_int(
        value: str | None,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        if value is None or not value.strip():
            return default
        try:
            parsed = int(value)
        except ValueError:
            return default
        return max(min(parsed, maximum), minimum)

    limit_value = _parse_int(
        values.get("limit") or request.query_params.get("limit"),
        default=20,
        minimum=1,
        maximum=100,
    )
    offset_value = _parse_int(
        values.get("offset") or request.query_params.get("offset"),
        default=0,
        minimum=0,
        maximum=10_000,
    )
    scope_raw = (values.get("scope") or request.query_params.get("scope") or "").lower()
    include_all = scope_raw in {"all", "true", "1", "yes"}
    if not include_all:
        include_all = request.query_params.get("all", "").lower() in {"1", "true", "all", "yes"}
    return limit_value, offset_value, include_all


__all__ = [
    "logger",
    "templates",
    "_LIVE_UPDATES_POLLING",
    "_LIVE_UPDATES_SSE",
    "_resolve_live_updates_mode",
    "_LiveFragmentBuilder",
    "_ui_event_stream",
    "_render_alert_fragment",
    "_ensure_csrf_token",
    "_parse_form_body",
    "_extract_download_refresh_params",
]
