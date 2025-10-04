import pytest

from app.utils.jsonx import safe_dumps, safe_loads, try_parse_json_or_none


def test_safe_dumps_sorts_keys():
    payload = {"b": 2, "a": 1}
    dumped = safe_dumps(payload)
    assert dumped == '{"a":1,"b":2}'


def test_safe_loads_rejects_blank():
    with pytest.raises(ValueError):
        safe_loads("  ")


def test_try_parse_json_or_none_returns_none():
    assert try_parse_json_or_none("not json") is None
    assert try_parse_json_or_none(None) is None
