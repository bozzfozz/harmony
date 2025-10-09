from __future__ import annotations

import os

from app.config import load_config
from app.integrations.registry import ProviderRegistry


def test_registry_enables_only_requested_providers(monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATIONS_ENABLED", "spotify")
    config = load_config()
    registry = ProviderRegistry(config=config)
    registry.initialise()

    providers = registry.track_providers()
    assert set(providers.keys()) == {"spotify"}


def test_registry_initialises_slskd_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("INTEGRATIONS_ENABLED", "slskd")
    monkeypatch.setenv("SLSKD_API_KEY", "dummy")
    monkeypatch.setenv(
        "SLSKD_BASE_URL", os.getenv("SLSKD_BASE_URL", "http://localhost:5030")
    )
    config = load_config()
    registry = ProviderRegistry(config=config)
    registry.initialise()

    providers = registry.track_providers()
    assert set(providers.keys()) == {"slskd"}
