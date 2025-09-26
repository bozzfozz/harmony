from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from app.config import ArtworkConfig, ArtworkFallbackConfig
from app.db import session_scope
from app.models import Download
from app.utils import artwork_utils
from app.workers.artwork_worker import ArtworkWorker


def test_download_flow_with_artwork(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client,
) -> None:
    audio_path = tmp_path / "flow.mp3"
    audio_path.write_bytes(b"audio")

    with session_scope() as session:
        download = Download(
            filename=str(audio_path),
            state="completed",
            progress=100.0,
            artwork_status="pending",
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    downloads: list[str] = []
    embeds: Dict[str, Any] = {}

    def fake_download(url: str, target: Path, **_: Any) -> Path:
        downloads.append(url)
        destination = target.with_suffix(".jpg")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"cover-bytes")
        return destination

    def fake_embed(audio_file: Path, artwork_file: Path) -> None:
        embeds["audio"] = Path(audio_file)
        embeds["artwork"] = Path(artwork_file)

    monkeypatch.setattr(artwork_utils, "download_artwork", fake_download)
    monkeypatch.setattr(artwork_utils, "embed_artwork", fake_embed)
    monkeypatch.setattr(artwork_utils, "extract_embed_info", lambda *_: None)

    async def process() -> None:
        config = ArtworkConfig(
            directory=str(tmp_path / "artwork"),
            timeout_seconds=5.0,
            max_bytes=5 * 1024 * 1024,
            concurrency=1,
            min_edge=600,
            min_bytes=120_000,
            fallback=ArtworkFallbackConfig(
                enabled=False,
                provider="none",
                timeout_seconds=5.0,
                max_bytes=5 * 1024 * 1024,
            ),
            poststep_enabled=False,
        )
        worker = ArtworkWorker(storage_directory=tmp_path / "artwork", config=config)
        await worker.start()
        try:
            await worker.enqueue(
                download_id,
                str(audio_path),
                metadata={"artwork_url": "http://example.com/cover.jpg"},
            )
            await worker.wait_for_pending()
        finally:
            await worker.stop()

    client._loop.run_until_complete(process())

    assert downloads == ["http://example.com/cover.jpg"]
    assert embeds["audio"] == audio_path
    artwork_path = embeds["artwork"]
    assert artwork_path.read_bytes() == b"cover-bytes"

    response = client.get(f"/soulseek/download/{download_id}/artwork")
    assert response.status_code == 200
    assert response._body == b"cover-bytes"
