import pytest

from app.integrations.slskd_adapter import SlskdAdapter


def _base_kwargs() -> dict[str, object]:
    return {
        "base_url": "https://example.com/api",
        "timeout_ms": 5000,
        "preferred_formats": ("FLAC", "MP3"),
        "max_results": 10,
    }


def test_slskd_adapter_trims_and_applies_api_key() -> None:
    adapter = SlskdAdapter(api_key="  secret-key  ", **_base_kwargs())

    assert adapter.api_key == "secret-key"
    assert adapter._headers["X-API-Key"] == "secret-key"
    assert adapter._headers["Accept"] == "application/json"


def test_slskd_adapter_allows_missing_api_key() -> None:
    adapter = SlskdAdapter(api_key=None, **_base_kwargs())

    assert adapter.api_key is None
    assert adapter._headers == {"Accept": "application/json"}


@pytest.mark.parametrize("base_url", ["", "ftp://example.com", "http://"])
def test_slskd_adapter_invalid_base_url_raises(base_url: str) -> None:
    with pytest.raises(RuntimeError):
        SlskdAdapter(
            api_key="token",
            base_url=base_url,
            timeout_ms=5000,
            preferred_formats=("MP3",),
            max_results=5,
        )
