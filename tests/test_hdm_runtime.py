from __future__ import annotations

from app.config import HdmConfig, SoulseekConfig
from app.hdm.move import AtomicFileMover
from app.hdm.pipeline_impl import DefaultDownloadPipeline
from app.hdm.runtime import build_hdm_runtime


def test_build_hdm_runtime_uses_atomic_file_mover(tmp_path):
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"

    config = HdmConfig(
        downloads_dir=str(downloads_dir),
        music_dir=str(music_dir),
        worker_concurrency=1,
        batch_max_items=1,
        size_stable_seconds=1,
        max_retries=1,
        slskd_timeout_seconds=5,
        move_template="{artist}/{album}/{track}",
    )

    soulseek = SoulseekConfig(
        base_url="http://localhost:5030",
        api_key=None,
        timeout_ms=1_000,
        retry_max=0,
        retry_backoff_base_ms=100,
        retry_jitter_pct=0.0,
        preferred_formats=("mp3",),
        max_results=10,
    )

    runtime = build_hdm_runtime(config, soulseek)

    assert isinstance(runtime.pipeline, DefaultDownloadPipeline)
    mover = getattr(runtime.pipeline, "_mover")
    assert isinstance(mover, AtomicFileMover)


def test_hdm_timeout_overrides_from_env(tmp_path):
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    env = {
        "DOWNLOADS_DIR": str(downloads_dir),
        "MUSIC_DIR": str(music_dir),
        "SLSKD_TIMEOUT_SEC": "42",
    }

    config = HdmConfig.from_env(env)
    assert config.slskd_timeout_seconds == 42

    soulseek = SoulseekConfig(
        base_url="http://localhost:5030",
        api_key=None,
        timeout_ms=1_000,
        retry_max=0,
        retry_backoff_base_ms=100,
        retry_jitter_pct=0.0,
        preferred_formats=("mp3",),
        max_results=10,
    )

    runtime = build_hdm_runtime(config, soulseek)
    slskd_client = getattr(runtime.pipeline, "_slskd")

    assert slskd_client is not None
    assert slskd_client.timeout_ms == 42 * 1000
