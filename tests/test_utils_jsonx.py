import pytest

from app.utils import jsonx


def test_safe_loads_accepts_utf16_bytes() -> None:
    payload = '{"answer": 42}'.encode("utf-16")
    assert jsonx.safe_loads(payload) == {"answer": 42}


def test_safe_loads_handles_bytearray_input() -> None:
    data = bytearray(b" [1, 2, 3] ")
    assert jsonx.safe_loads(data) == [1, 2, 3]


@pytest.mark.parametrize("data", [b"   ", bytearray(b"   ")])
def test_safe_loads_rejects_blank_byte_sequences(data: bytes | bytearray) -> None:
    with pytest.raises(ValueError):
        jsonx.safe_loads(data)
