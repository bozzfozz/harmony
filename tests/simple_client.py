from __future__ import annotations

import asyncio
import json
from types import TracebackType
from typing import Any, Dict, Optional, Type
from urllib.parse import urlencode

from fastapi import FastAPI


class SimpleResponse:
    def __init__(self, status_code: int, body: bytes, headers: Dict[str, str]) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = headers

    def json(self) -> Any:
        if not self._body:
            return None
        return json.loads(self._body.decode("utf-8"))


class SimpleTestClient:
    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self._loop = asyncio.new_event_loop()
        self._previous_loop: Optional[asyncio.AbstractEventLoop] = None

    def __enter__(self) -> "SimpleTestClient":
        try:
            self._previous_loop = asyncio.get_event_loop()
        except RuntimeError:
            self._previous_loop = None
        asyncio.get_event_loop_policy().set_event_loop(self._loop)
        self._loop.run_until_complete(self.app.router.startup())
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self._loop.run_until_complete(self.app.router.shutdown())
        self._loop.close()
        if self._previous_loop is not None:
            asyncio.get_event_loop_policy().set_event_loop(self._previous_loop)

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> SimpleResponse:
        return self._loop.run_until_complete(self._request("GET", path, params=params))

    def post(
        self,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> SimpleResponse:
        payload = json_body if json_body is not None else json
        return self._loop.run_until_complete(self._request("POST", path, json_body=payload))

    def put(self, path: str, json: Optional[Dict[str, Any]] = None) -> SimpleResponse:
        return self._loop.run_until_complete(self._request("PUT", path, json_body=json))

    def delete(self, path: str) -> SimpleResponse:
        return self._loop.run_until_complete(self._request("DELETE", path))

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> SimpleResponse:
        query_string = urlencode(params or {})
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": query_string.encode("utf-8"),
            "headers": [],
        }

        body = b""
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            scope["headers"].append((b"content-type", b"application/json"))

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
                response_headers = {key.decode(): value.decode() for key, value in message.get("headers", [])}
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))

        await self.app(scope, receive, send)
        return SimpleResponse(status_code, bytes(response_body), response_headers)
