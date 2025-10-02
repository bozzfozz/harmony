import pytest

from app.utils.idempotency import make_idempotency_key


def test_make_idempotency_key_is_stable():
    first = make_idempotency_key("alpha", "beta")
    second = make_idempotency_key("alpha", "beta")
    assert first == second
    assert len(first) == 32


def test_make_idempotency_key_differs_for_parts():
    key_one = make_idempotency_key("alpha", "one")
    key_two = make_idempotency_key("alpha", "two")
    assert key_one != key_two


def test_make_idempotency_key_accepts_bytes():
    key = make_idempotency_key("prefix", b"binary")
    assert isinstance(key, str)
    assert len(key) == 32


def test_make_idempotency_key_requires_parts():
    with pytest.raises(ValueError):
        make_idempotency_key()
