import pytest

from app.config import IntegrationsConfig, load_config
from app.integrations.registry import ProviderRegistry


class _MockProvider:
    name = "mock"

    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1

    async def search_tracks(self, query):  # pragma: no cover - protocol stub
        return []

    async def fetch_artist(self, *, artist_id=None, name=None):  # pragma: no cover - protocol stub
        return None

    async def fetch_artist_releases(
        self, artist_source_id, *, limit=None
    ):  # pragma: no cover - protocol stub
        return []

    async def fetch_album(self, album_source_id):  # pragma: no cover - protocol stub
        return None

    async def fetch_artist_top_tracks(
        self, artist_source_id, *, limit=None
    ):  # pragma: no cover - protocol stub
        return []


class _SoulseekMockProvider(_MockProvider):
    name = "slskd"


@pytest.mark.asyncio
async def test_registry_shutdown_invokes_adapter_aclose(monkeypatch):
    config = load_config()
    config.integrations = IntegrationsConfig(
        enabled=("mock",),
        timeouts_ms={},
        max_concurrency=1,
    )

    adapter = _MockProvider()

    def _build_provider(self, name: str):
        if name == "mock":
            return adapter
        return None

    monkeypatch.setattr(ProviderRegistry, "_build_track_provider", _build_provider)

    registry = ProviderRegistry(config=config)
    registry.initialise()

    await registry.shutdown()
    await registry.shutdown()

    assert adapter.close_calls == 1


def test_registry_resolves_soulseek_alias_and_canonical(monkeypatch):
    config = load_config()
    config.integrations = IntegrationsConfig(
        enabled=("soulseek",),
        timeouts_ms={},
        max_concurrency=1,
    )

    adapter = _SoulseekMockProvider()

    def _build_provider(self, name: str):
        if name.lower() in {"soulseek", "slskd"}:
            return adapter
        return None

    monkeypatch.setattr(ProviderRegistry, "_build_track_provider", _build_provider)

    registry = ProviderRegistry(config=config)

    alias_instance = registry.get_track_provider("soulseek")
    canonical_instance = registry.get_track_provider("slskd")

    assert alias_instance is canonical_instance


def test_registry_unknown_provider_raises(monkeypatch):
    config = load_config()
    config.integrations = IntegrationsConfig(
        enabled=("soulseek",),
        timeouts_ms={},
        max_concurrency=1,
    )

    adapter = _SoulseekMockProvider()

    def _build_provider(self, name: str):
        if name.lower() == "soulseek":
            return adapter
        return None

    monkeypatch.setattr(ProviderRegistry, "_build_track_provider", _build_provider)

    registry = ProviderRegistry(config=config)

    with pytest.raises(KeyError):
        registry.get_track_provider("unknown")
