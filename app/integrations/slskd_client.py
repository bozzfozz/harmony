"""Async HTTP client for the slskd search API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import httpx


class SlskdClientError(RuntimeError):
    """Base exception raised for slskd client failures."""


class SlskdTimeoutError(SlskdClientError):
    """Raised when a request exceeded the configured timeout."""


class SlskdInvalidResponseError(SlskdClientError):
    """Raised when the upstream payload cannot be decoded as JSON."""


class SlskdHTTPStatusError(SlskdClientError):
    """Raised when the upstream service returned an unexpected status code."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.body = body


class SlskdRateLimitedError(SlskdHTTPStatusError):
    """Raised when slskd rejected the request due to rate limits."""

    def __init__(self, *, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(429, "slskd rate limited the request", headers=headers)


@dataclass(slots=True)
class SlskdHttpClient:
    """Thin HTTPX wrapper tailored to the slskd search endpoint."""

    base_url: str
    api_key: str | None = None
    transport: httpx.AsyncBaseTransport | None = None

    async def search_tracks(self, query: str, *, limit: int, timeout_ms: int) -> Any:
        """Issue a search request against slskd and return the JSON payload."""

        timeout = self._build_timeout(timeout_ms)
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        params = {"query": query, "limit": limit}
        base_url = self.base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=timeout,
                headers=headers,
                transport=self.transport,
            ) as client:
                response = await client.get("/api/v0/search/tracks", params=params)
        except httpx.TimeoutException as exc:
            raise SlskdTimeoutError("slskd search request timed out") from exc
        except httpx.HTTPError as exc:
            raise SlskdClientError(f"slskd request failed: {exc}") from exc

        if response.status_code == httpx.codes.OK:
            try:
                return response.json()
            except ValueError as exc:  # pragma: no cover - defensive guard
                raise SlskdInvalidResponseError("slskd returned invalid JSON") from exc

        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise SlskdRateLimitedError(headers=response.headers)

        body_preview = response.text[:200]
        if 500 <= response.status_code < 600:
            raise SlskdHTTPStatusError(
                response.status_code,
                "slskd returned a server error",
                headers=response.headers,
                body=body_preview,
            )
        if 400 <= response.status_code < 500:
            raise SlskdHTTPStatusError(
                response.status_code,
                "slskd rejected the search request",
                headers=response.headers,
                body=body_preview,
            )
        raise SlskdHTTPStatusError(
            response.status_code,
            "slskd responded with an unexpected status",
            headers=response.headers,
            body=body_preview,
        )

    @staticmethod
    def _build_timeout(timeout_ms: int) -> httpx.Timeout:
        timeout_seconds = max(timeout_ms, 100) / 1000
        connect_timeout = min(timeout_seconds, 5.0)
        return httpx.Timeout(
            timeout_seconds,
            connect=connect_timeout,
            read=timeout_seconds,
            write=timeout_seconds,
        )


__all__ = [
    "SlskdClientError",
    "SlskdHttpClient",
    "SlskdHTTPStatusError",
    "SlskdInvalidResponseError",
    "SlskdRateLimitedError",
    "SlskdTimeoutError",
]
