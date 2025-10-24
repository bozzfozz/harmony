from __future__ import annotations

import sys
import types

import pytest


def _install_sqlalchemy_stub() -> None:
    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.create_engine = lambda *args, **kwargs: None  # type: ignore[assignment]
    sqlalchemy_stub.text = lambda statement: statement  # type: ignore[assignment]

    engine_stub = types.ModuleType("sqlalchemy.engine")
    engine_stub.make_url = lambda url: url  # type: ignore[assignment]

    exc_stub = types.ModuleType("sqlalchemy.exc")

    class SQLAlchemyError(Exception):
        pass

    class ArgumentError(SQLAlchemyError):
        pass

    exc_stub.SQLAlchemyError = SQLAlchemyError  # type: ignore[attr-defined]
    exc_stub.ArgumentError = ArgumentError  # type: ignore[attr-defined]

    sys.modules.setdefault("sqlalchemy", sqlalchemy_stub)
    sys.modules.setdefault("sqlalchemy.engine", engine_stub)
    sys.modules.setdefault("sqlalchemy.exc", exc_stub)


_install_sqlalchemy_stub()

from app.config import _normalise_public_base


@pytest.mark.parametrize(
    ("raw", "api_base", "expected"),
    [
        (None, "/api/v1", "/api/v1/oauth"),
        ("", "/api/v1", "/api/v1/oauth"),
        ("/custom/oauth", "/api/v1", "/custom/oauth"),
        ("oauth", "/api/v1", "/oauth"),
        ("/", "/api/v1", "/"),
        (
            "https://harmony.example.com/api/v1/oauth",
            "/api/v1",
            "https://harmony.example.com/api/v1/oauth",
        ),
        (
            "https://harmony.example.com/api/v1/oauth/",
            "/api/v1",
            "https://harmony.example.com/api/v1/oauth",
        ),
        ("https://harmony.example.com", "/api/v1", "https://harmony.example.com"),
        ("https://harmony.example.com/", "", "https://harmony.example.com"),
        ("https://harmony.example.com/path?foo=bar", "", "https://harmony.example.com/path"),
        ("https:///broken/path", "", "/broken/path"),
        ("   https://harmony.example.com/base   ", "", "https://harmony.example.com/base"),
        (None, "", "/oauth"),
    ],
)
def test_normalise_public_base(raw: str | None, api_base: str, expected: str) -> None:
    assert _normalise_public_base(raw, api_base_path=api_base) == expected
