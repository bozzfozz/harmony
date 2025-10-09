from __future__ import annotations

import asyncio
import json
import os
from collections import OrderedDict
from types import TracebackType
from typing import Any, AsyncContextManager, Dict, Mapping, Optional, Type

os.environ.setdefault("HARMONY_API_KEYS", "test-key")
from urllib.parse import urlencode

from fastapi import FastAPI
from tests.helpers import api_path


class SimpleResponse:
    def __init__(self, status_code: int, body: bytes, headers: Dict[str, str]) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = headers

    def json(self) -> Any:
        if not self._body:
            return None
        return json.loads(self._body.decode("utf-8"))

    @property
    def text(self) -> str:
        if not self._body:
            return ""
        return self._body.decode("utf-8")


class SimpleTestClient:
    def __init__(
        self,
        app: FastAPI,
        *,
        default_headers: Optional[Mapping[str, str]] = None,
        include_env_api_key: bool = True,
    ) -> None:
        self.app = app
        self._loop = asyncio.new_event_loop()
        self._previous_loop: Optional[asyncio.AbstractEventLoop] = None
        self._lifespan_context: Optional[AsyncContextManager[None]] = None
        headers = {k.lower(): v for k, v in (default_headers or {}).items()}
        if include_env_api_key and "x-api-key" not in headers:
            headers.update(_resolve_default_headers())
        self._default_headers = headers

    def __enter__(self) -> "SimpleTestClient":
        try:
            self._previous_loop = asyncio.get_event_loop()
        except RuntimeError:
            self._previous_loop = None
        asyncio.get_event_loop_policy().set_event_loop(self._loop)
        lifespan_factory = getattr(self.app.router, "lifespan_context", None)
        if callable(lifespan_factory):
            self._lifespan_context = lifespan_factory(self.app)
            self._loop.run_until_complete(self._lifespan_context.__aenter__())
        else:
            self._loop.run_until_complete(self.app.router.startup())
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if self._lifespan_context is not None:
            self._loop.run_until_complete(
                self._lifespan_context.__aexit__(exc_type, exc, tb)
            )
            self._lifespan_context = None
        else:
            self._loop.run_until_complete(self.app.router.shutdown())
        self._loop.close()
        if self._previous_loop is not None:
            asyncio.get_event_loop_policy().set_event_loop(self._previous_loop)

    def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        *,
        use_raw_path: bool = False,
    ) -> SimpleResponse:
        return self._loop.run_until_complete(
            self._request(
                "GET",
                path,
                params=params,
                headers=headers,
                use_raw_path=use_raw_path,
            )
        )

    def post(
        self,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[bytes | str] = None,
        content_type: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        *,
        use_raw_path: bool = False,
    ) -> SimpleResponse:
        payload = json_body if json_body is not None else json
        return self._loop.run_until_complete(
            self._request(
                "POST",
                path,
                params=params,
                json_body=payload,
                raw_body=data,
                content_type=content_type,
                headers=headers,
                use_raw_path=use_raw_path,
            )
        )

    def put(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        *,
        use_raw_path: bool = False,
    ) -> SimpleResponse:
        return self._loop.run_until_complete(
            self._request(
                "PUT",
                path,
                json_body=json,
                headers=headers,
                use_raw_path=use_raw_path,
            )
        )

    def patch(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        *,
        use_raw_path: bool = False,
    ) -> SimpleResponse:
        return self._loop.run_until_complete(
            self._request(
                "PATCH",
                path,
                json_body=json,
                headers=headers,
                use_raw_path=use_raw_path,
            )
        )

    def delete(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        *,
        use_raw_path: bool = False,
    ) -> SimpleResponse:
        return self._loop.run_until_complete(
            self._request(
                "DELETE",
                path,
                json_body=json,
                headers=headers,
                use_raw_path=use_raw_path,
            )
        )

    def options(
        self,
        path: str,
        headers: Optional[Mapping[str, str]] = None,
        *,
        use_raw_path: bool = False,
    ) -> SimpleResponse:
        return self._loop.run_until_complete(
            self._request(
                "OPTIONS",
                path,
                headers=headers,
                use_raw_path=use_raw_path,
            )
        )

    def head(
        self,
        path: str,
        headers: Optional[Mapping[str, str]] = None,
        *,
        use_raw_path: bool = False,
    ) -> SimpleResponse:
        return self._loop.run_until_complete(
            self._request(
                "HEAD",
                path,
                headers=headers,
                use_raw_path=use_raw_path,
            )
        )

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        raw_body: Optional[bytes | str] = None,
        content_type: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        *,
        use_raw_path: bool = False,
    ) -> SimpleResponse:
        resolved_path = path
        if not use_raw_path and not path.startswith("http"):
            resolved_path = api_path(path)
        if not resolved_path.startswith("/"):
            resolved_path = f"/{resolved_path}"

        query_string = urlencode(params or {})
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "path": resolved_path,
            "raw_path": resolved_path.encode("utf-8"),
            "query_string": query_string.encode("utf-8"),
            "headers": [],
        }

        header_items: OrderedDict[bytes, bytes] = OrderedDict()
        for source in (
            self._default_headers,
            {k.lower(): v for k, v in (headers or {}).items()},
        ):
            for key, value in source.items():
                header_items[key.encode("latin-1")] = value.encode("utf-8")

        if header_items:
            scope["headers"] = list(header_items.items())

        body = b""
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            scope["headers"].append((b"content-type", b"application/json"))
        elif raw_body is not None:
            body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
            if content_type:
                scope["headers"].append((b"content-type", content_type.encode("utf-8")))
        elif content_type:
            scope["headers"].append((b"content-type", content_type.encode("utf-8")))

        response_body = bytearray()
        response_headers: Dict[str, str] = {}
        status_code = 500
        request_complete = False

        async def receive() -> Dict[str, Any]:
            nonlocal request_complete
            if request_complete:
                return {"type": "http.disconnect"}
            request_complete = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: Dict[str, Any]) -> None:
            nonlocal status_code, response_headers
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = {
                    key.decode(): value.decode()
                    for key, value in message.get("headers", [])
                }
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))

        await self.app(scope, receive, send)
        body_bytes = bytes(response_body)
        headers = dict(response_headers)
        if "ETag" not in headers:
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                payload = None
            if isinstance(payload, dict):
                etag_value = payload.get("etag") or payload.get("ETag")
                if isinstance(etag_value, str) and etag_value:
                    headers["ETag"] = etag_value
        return SimpleResponse(status_code, body_bytes, headers)


def _resolve_default_headers() -> Dict[str, str]:
    try:
        from app import dependencies as deps
    except Exception:
        return {}

    config = deps.get_app_config()
    if config.security.api_keys:
        return {"x-api-key": config.security.api_keys[0]}
    return {}
