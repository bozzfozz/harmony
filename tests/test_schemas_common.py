"""Validation tests for schema primitives."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
import pytest

from app.schemas.common import ID, URI, ISODateTime


class SampleModel(BaseModel):
    identifier: ID
    resource: URI
    timestamp: ISODateTime


class TestID:
    def test_accepts_string_like_inputs(self) -> None:
        result = ID.validate("  foo  ")
        assert isinstance(result, ID)
        assert result == "foo"

    def test_decodes_bytes(self) -> None:
        result = ID.validate(b"bar\n")
        assert result == "bar"

    def test_rejects_non_string(self) -> None:
        with pytest.raises(TypeError, match="identifier must be a string"):
            ID.validate(42)

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="identifier must not be empty"):
            ID.validate("   ")


class TestURI:
    def test_valid_uri(self) -> None:
        result = URI.validate(" https://example.com/path ")
        assert result == "https://example.com/path"

    def test_missing_host(self) -> None:
        with pytest.raises(ValueError, match="uri must include scheme and host"):
            URI.validate("https:/invalid")

    def test_type_error(self) -> None:
        with pytest.raises(TypeError, match="uri must be a string"):
            URI.validate(123)


class TestISODateTime:
    def test_accepts_datetime(self) -> None:
        naive = datetime(2024, 1, 1, 12, 30, 0)
        result = ISODateTime.validate(naive)
        assert result == "2024-01-01T12:30:00+00:00"

    def test_accepts_string(self) -> None:
        result = ISODateTime.validate("2024-01-01T12:30:00Z")
        assert result == "2024-01-01T12:30:00+00:00"

    def test_rejects_invalid_string(self) -> None:
        with pytest.raises(ValueError, match="invalid ISO 8601 datetime"):
            ISODateTime.validate("not-a-date")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="datetime must not be empty"):
            ISODateTime.validate("   ")

    def test_type_error(self) -> None:
        with pytest.raises(TypeError, match="datetime must be string or datetime"):
            ISODateTime.validate(object())


def test_json_schema_metadata() -> None:
    schema = SampleModel.model_json_schema()
    id_schema = schema["properties"]["identifier"]
    uri_schema = schema["properties"]["resource"]
    dt_schema = schema["properties"]["timestamp"]

    assert id_schema["type"] == "string"
    assert id_schema["title"] == "ID"

    assert uri_schema["format"] == "uri"
    assert uri_schema["title"] == "URI"

    assert dt_schema["format"] == "date-time"
    assert dt_schema["title"] == "ISODateTime"
    assert dt_schema["type"] == "string"
