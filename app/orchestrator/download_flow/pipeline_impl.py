"""Concrete implementation of the :class:`DownloadPipeline` protocol."""

from __future__ import annotations

from pathlib import Path

from .completion import (
    DownloadCompletionMonitor,
    build_item_event,
    record_detection_event,
)
from .dedup import DeduplicationManager
from .models import DownloadOutcome, DownloadWorkItem
from .move import AtomicFileMover
from .pipeline import DownloadPipeline
from .recovery import SidecarStore
from .tagging import AudioTagger
class DefaultDownloadPipeline(DownloadPipeline):
    """Pipeline chaining download detection, tagging, moving and dedupe."""

    def __init__(
        self,
        *,
        completion_monitor: DownloadCompletionMonitor,
        tagger: AudioTagger,
        mover: AtomicFileMover,
        deduper: DeduplicationManager,
        sidecars: SidecarStore,
    ) -> None:
        self._completion = completion_monitor
        self._tagger = tagger
        self._mover = mover
        self._deduper = deduper
        self._sidecars = sidecars

    async def execute(self, work_item: DownloadWorkItem) -> DownloadOutcome:  # type: ignore[override]
        item = work_item.item
        sidecar = await self._sidecars.load(item, attempt=work_item.attempt)

        async with await self._deduper.acquire_lock(item):
            existing = await self._deduper.lookup_existing(item.dedupe_key)
            if existing is not None and existing.exists():
                work_item.record_event(
                    "dedupe.skip",
                    meta={
                        "final_path": str(existing),
                    },
                )
                return DownloadOutcome(
                    final_path=existing,
                    tags_written=False,
                    bytes_written=0,
                    track_duration_seconds=None,
                    quality=None,
                    events=(build_item_event("dedupe.skip", final_path=str(existing)),),
                )

            expected_path = Path(sidecar.source_path) if sidecar.source_path else None
            completion = await self._completion.wait_for_completion(
                work_item, expected_path=expected_path
            )
            record_detection_event(
                work_item, path=completion.path, bytes_written=completion.bytes_written
            )
            sidecar.mark(status="downloaded", source_path=completion.path)
            sidecar.bytes_written = completion.bytes_written
            await self._sidecars.save(sidecar)

            tagging = self._tagger.apply_tags(completion.path, item)
            if tagging.applied:
                work_item.record_event(
                    "tagging.completed",
                    meta={
                        "codec": tagging.codec,
                        "bitrate": tagging.bitrate,
                    },
                )
            else:
                work_item.record_event("tagging.skipped")

            destination = self._deduper.plan_destination(item, completion.path)
            final_path = self._mover.move(completion.path, destination)
            work_item.record_event(
                "file.moved",
                meta={
                    "destination": str(final_path),
                },
            )

            await self._deduper.register_completion(item.dedupe_key, final_path)
            sidecar.set_final(final_path, completion.bytes_written)
            await self._sidecars.save(sidecar)

            duration = tagging.duration_seconds or completion.duration_seconds
            quality = _format_quality(tagging.codec, tagging.bitrate)
            events = (
                build_item_event(
                    "tagging.completed" if tagging.applied else "tagging.skipped",
                    codec=tagging.codec,
                    bitrate=tagging.bitrate,
                ),
                build_item_event("file.moved", destination=str(final_path)),
            )
            return DownloadOutcome(
                final_path=final_path,
                tags_written=tagging.applied,
                bytes_written=completion.bytes_written,
                track_duration_seconds=duration,
                quality=quality,
                events=events,
            )


def _format_quality(codec: str | None, bitrate: int | None) -> str | None:
    if codec and bitrate:
        return f"{codec}/{bitrate}"
    if codec:
        return str(codec)
    if bitrate:
        return f"{bitrate}kbps"
    return None


__all__ = ["DefaultDownloadPipeline"]

