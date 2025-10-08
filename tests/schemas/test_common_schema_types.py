from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas.common import ID, URI, ISODateTime


@pytest.mark.parametrize(
    "value, expected",
    [("abc", "abc"), (b" abc ", "abc"), (ID("xyz"), "xyz")],
)
def test_id_validate_normalises_input(value, expected) -> None:
    assert ID.validate(value) == expected


@pytest.mark.parametrize("value", ["", b"   ", None, 1])
def test_id_validate_rejects_invalid_values(value) -> None:
    with pytest.raises((TypeError, ValueError)):
        ID.validate(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value, expected",
    [("https://example.com", "https://example.com"), (b" http://foo/ ", "http://foo/")],
)
def test_uri_validate_accepts_well_formed_values(value, expected) -> None:
    assert URI.validate(value) == expected


@pytest.mark.parametrize("value", ["ftp:/broken", "", 123])
def test_uri_validate_rejects_invalid_values(value) -> None:
    with pytest.raises((TypeError, ValueError)):
        URI.validate(value)  # type: ignore[arg-type]


def test_iso_datetime_from_datetime_object() -> None:
    dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert ISODateTime.validate(dt) == dt.isoformat()


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2024-01-01T00:00:00Z", "2024-01-01T00:00:00+00:00"),
        (b"2024-01-01T12:00:00+01:00", "2024-01-01T12:00:00+01:00"),
    ],
)
def test_iso_datetime_from_string(value, expected) -> None:
    assert ISODateTime.validate(value) == expected


@pytest.mark.parametrize("value", ["", "not-a-date", 42])
def test_iso_datetime_rejects_invalid_values(value) -> None:
    with pytest.raises((TypeError, ValueError)):
        ISODateTime.validate(value)  # type: ignore[arg-type]
