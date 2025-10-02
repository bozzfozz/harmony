import pytest

from app.utils.jsonx import safe_dumps, safe_loads, try_parse_json_or_none
from app.utils.validate import clamp_int, positive_int, require_non_empty


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


def test_clamp_int():
    assert clamp_int(5, 1, 10) == 5
    assert clamp_int(-1, 0, 3) == 0
    assert clamp_int(9, 0, 3) == 3
    with pytest.raises(ValueError):
        clamp_int(5, 10, 1)


def test_require_non_empty():
    assert require_non_empty("name", " value ") == "value"
    with pytest.raises(ValueError):
        require_non_empty("name", "   ")


def test_positive_int():
    assert positive_int(3) == 3
    with pytest.raises(ValueError):
        positive_int(0)
