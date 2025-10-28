import pytest

from app.utils import jsonx


def test_safe_loads_accepts_utf16_bytes() -> None:
    payload = '{"answer": 42}'.encode("utf-16")
    assert jsonx.safe_loads(payload) == {"answer": 42}


def test_safe_loads_handles_bytearray_input() -> None:
    data = bytearray(b" [1, 2, 3] ")
    assert jsonx.safe_loads(data) == [1, 2, 3]


def test_safe_loads_handles_memoryview_input() -> None:
    payload = memoryview(b" [4, 5, 6] ")
    assert jsonx.safe_loads(payload) == [4, 5, 6]


@pytest.mark.parametrize("data", [b"   ", bytearray(b"   "), memoryview(b"   ")])
def test_safe_loads_rejects_blank_byte_sequences(
    data: bytes | bytearray | memoryview,
) -> None:
    with pytest.raises(ValueError):
        jsonx.safe_loads(data)


def test_safe_dumps_serialises_sets_as_lists() -> None:
    payload = {"values": {3, 1, 2}}
    data = jsonx.safe_dumps(payload)
    assert data == "{\"values\":[1,2,3]}"
    assert jsonx.safe_loads(data) == {"values": [1, 2, 3]}


def test_safe_dumps_handles_frozenset() -> None:
    payload = {"values": frozenset({"b", "a"})}
    data = jsonx.safe_dumps(payload)
    assert jsonx.safe_loads(data) == {"values": ["a", "b"]}


def test_safe_dumps_handles_dict_keys_view() -> None:
    mapping = {"b": 1, "a": 2}
    data = jsonx.safe_dumps({"keys": mapping.keys()})
    assert jsonx.safe_loads(data) == {"keys": ["a", "b"]}
