import asyncio
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException

from app.core.beets_client import BeetsClient
from app.core.soulseek_client import SoulseekClient, TrackResult
from app.core.spotify_client import SpotifyClient, Track
from app.core.plex_client import PlexClient
from app.utils.logging_config import get_logger

logger = get_logger("sync_worker")


class SyncWorker:
    """Coordinate the end-to-end track synchronisation pipeline."""

    def __init__(self) -> None:
        self.spotify = SpotifyClient()
        self.soulseek = SoulseekClient()
        self.plex = PlexClient()
        self.beets = BeetsClient()

    async def sync_track(self, spotify_track_id: str) -> dict[str, object]:
        """Download a Spotify track via Soulseek and import it into Beets.

        The real Harmony service performs a considerable amount of IO, but for
        the purposes of these kata style exercises the integrations are light
        weight and run entirely in memory.  The orchestration still mirrors the
        expected control flow so that higher level behaviour can be verified in
        tests.
        """

        track = self.spotify.get_track(spotify_track_id)
        if track is None:
            logger.error("Spotify track %s not found", spotify_track_id)
            raise HTTPException(status_code=404, detail="Spotify track not found")

        logger.info("Spotify track resolved: %s - %s", track.title, track.artist)

        results = await self.soulseek.search(track.title, timeout=30)
        if not results:
            logger.error("No Soulseek results found for %s", track.title)
            raise HTTPException(status_code=404, detail="No Soulseek results found")

        best_result = self._select_best_result(track, results)
        logger.info("Best Soulseek result: %s from %s", best_result.filename, best_result.username)

        download_success = await self.soulseek.download(
            username=best_result.username,
            filename=best_result.filename,
            size=best_result.size,
        )
        if not download_success:
            logger.error("Soulseek download failed for %s", best_result.filename)
            raise HTTPException(status_code=500, detail="Download failed")

        local_path = self.soulseek.download_path / best_result.filename
        tagged_path = await self._import_with_beets(local_path)

        plex_refreshed = await self._refresh_plex_if_supported()

        return {
            "status": "success",
            "spotify_track": track.title,
            "downloaded_file": str(local_path),
            "tagged_file": tagged_path,
            "plex_refreshed": plex_refreshed,
        }

    def _select_best_result(self, spotify_track: Track, results: Iterable[TrackResult]) -> TrackResult:
        """Pick the best Soulseek match using a fuzzy title/artist comparison."""

        def score(result: TrackResult) -> float:
            filename = Path(result.filename).stem
            title_ratio = SequenceMatcher(None, spotify_track.title.lower(), filename.lower()).ratio()
            artist_bonus = 0.1 if spotify_track.artist.lower() in filename.lower() else 0.0
            availability_bonus = 0.05 if result.free_upload_slots > 0 else 0.0
            return title_ratio + artist_bonus + availability_bonus

        return max(results, key=score)

    async def _import_with_beets(self, file_path: Path) -> str:
        """Import the downloaded file using the Beets client."""

        try:
            return await asyncio.to_thread(self.beets.import_file, file_path)
        except Exception as exc:  # pragma: no cover - defensive safety net
            logger.error("Beets import failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def _refresh_plex_if_supported(self) -> bool:
        """Refresh the Plex library if the client exposes a helper method."""

        refresh = getattr(self.plex, "refresh_library", None)
        if callable(refresh):
            try:
                result = await asyncio.to_thread(refresh)
            except Exception as exc:  # pragma: no cover - defensive safety net
                logger.warning("Plex refresh failed: %s", exc)
                return False
            return bool(result)
        return False
