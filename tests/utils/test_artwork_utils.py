from __future__ import annotations

from typing import Any

from app.utils import artwork_utils


class _DummyResponse:
    def raise_for_status(self) -> None:  # pragma: no cover - no-op
        return None

    def json(self) -> dict[str, Any]:  # pragma: no cover - deterministic payload
        return {}


class _DummyClient:
    def __init__(self) -> None:
        self.response = _DummyResponse()
        self.request: tuple[str, dict[str, Any]] | None = None

    def __enter__(self) -> "_DummyClient":  # pragma: no cover - context manager helper
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - context manager helper
        return None

    def get(self, url: str, params: dict[str, Any]) -> _DummyResponse:
        self.request = (url, params)
        return self.response


def test_fetch_caa_artwork_skips_disallowed_hosts(monkeypatch) -> None:
    release_groups = [{"id": "first"}, {"id": "second"}]

    monkeypatch.setattr(artwork_utils.httpx, "Client", lambda **_: _DummyClient())
    monkeypatch.setattr(artwork_utils, "_extract_release_groups", lambda payload: release_groups)
    monkeypatch.setattr(artwork_utils, "_extract_release_group_id", lambda entry: entry.get("id"))

    checked_urls: list[str] = []

    def fake_allowed_remote_host(url: str) -> bool:
        checked_urls.append(url)
        # Only allow the second URL; first should be skipped
        return len(checked_urls) > 1

    monkeypatch.setattr(artwork_utils, "allowed_remote_host", fake_allowed_remote_host)

    result = artwork_utils.fetch_caa_artwork("Artist", "Album")

    expected_urls = [
        "https://coverartarchive.org/release-group/first/front",
        "https://coverartarchive.org/release-group/second/front",
    ]

    assert checked_urls == expected_urls
    assert result == expected_urls[1]
