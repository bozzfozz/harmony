from __future__ import annotations

import pytest

from app.db import run_session
from app.models import Setting
from app.utils.service_health import evaluate_service_health


def _seed_settings(session, entries: dict[str, str | None]) -> None:
    session.add_all(Setting(key=key, value=value) for key, value in entries.items())
    session.commit()


@pytest.mark.asyncio
async def test_evaluate_service_health_uses_env_for_optional_secret() -> None:
    await run_session(lambda session: _seed_settings(session, {"SLSKD_URL": "http://localhost"}))

    env = {"SLSKD_API_KEY": "env-key"}

    health = await run_session(
        lambda session: evaluate_service_health(session, "soulseek", env=env)
    )

    assert health.status == "ok"
    assert health.optional_missing == ()


@pytest.mark.asyncio
async def test_evaluate_service_health_treats_blank_env_as_missing() -> None:
    await run_session(lambda session: _seed_settings(session, {"SLSKD_URL": "http://localhost"}))

    env = {"SLSKD_API_KEY": "   "}

    health = await run_session(
        lambda session: evaluate_service_health(session, "soulseek", env=env)
    )

    assert health.optional_missing == ("SLSKD_API_KEY",)


@pytest.mark.asyncio
async def test_evaluate_service_health_uses_env_for_required_setting() -> None:
    env = {"SLSKD_URL": "http://env.example"}

    health = await run_session(
        lambda session: evaluate_service_health(session, "soulseek", env=env)
    )

    assert health.status == "ok"
    assert health.missing == ()
