from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from app.integrations import slskd_client


def test_parse_retry_after_ms_numeric_value() -> None:
    headers = {"Retry-After": 3}

    assert slskd_client._parse_retry_after_ms(headers) == 3_000


def test_parse_retry_after_ms_string_value() -> None:
    headers = {"Retry-After": "4"}

    assert slskd_client._parse_retry_after_ms(headers) == 4_000


def test_parse_retry_after_ms_http_date(monkeypatch: pytest.MonkeyPatch) -> None:
    base_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    retry_after = base_time + timedelta(seconds=90)
    header_value = format_datetime(retry_after, usegmt=True)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            if tz is None:
                return base_time.replace(tzinfo=None)
            return base_time.astimezone(tz)

    monkeypatch.setattr(slskd_client, "datetime", _FrozenDatetime)

    assert slskd_client._parse_retry_after_ms({"Retry-After": header_value}) == 90_000
