"""Discography download worker."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.db import session_scope
from app.logging import get_logger
from app.models import DiscographyJob
from app.routers.matching_router import calculate_discography_missing
from app.workers.artwork_worker import ArtworkWorker
from app.workers.lyrics_worker import LyricsWorker

logger = get_logger(__name__)


class DiscographyWorker:
    """Process discography download jobs.

    The worker relies on Spotify to provide the complete discography for an
    artist.  Plex is queried to determine which tracks are already present.
    Missing tracks are fetched from Soulseek and then handed over to Beets for
    post-processing.
    """

    def __init__(
        self,
        spotify_client: SpotifyClient,
        soulseek_client: SoulseekClient,
        *,
        plex_client: Any | None = None,
        beets_client: Any | None = None,
        artwork_worker: ArtworkWorker | None = None,
        lyrics_worker: LyricsWorker | None = None,
    ) -> None:
        self._spotify = spotify_client
        self._soulseek = soulseek_client
        self._plex = plex_client
        self._beets = beets_client
        self._artwork = artwork_worker
        self._lyrics = lyrics_worker
        self._queue: asyncio.Queue[Optional[int]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        await self._queue.put(None)
        if self._task is not None:
            await self._task
            self._task = None

    async def enqueue(self, job_id: int) -> None:
        await self._queue.put(int(job_id))

    async def run_job(self, job_id: int) -> None:
        await self._process_job(int(job_id))

    async def _run(self) -> None:
        while self._running:
            job_id = await self._queue.get()
            if job_id is None:
                break
            try:
                await self._process_job(job_id)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Discography job %s failed: %s", job_id, exc)

    async def _process_job(self, job_id: int) -> None:
        job = self._set_status(job_id, "in_progress")
        if job is None:
            return

        artist_id = job.artist_id
        artist_name = job.artist_name or ""

        logger.info("Processing discography job %s for artist %s", job_id, artist_id)

        try:
            discography = self._spotify.get_artist_discography(artist_id)
            albums = discography.get("albums") if isinstance(discography, dict) else []
            plex_items = await self._fetch_existing_tracks(artist_name)
            missing_albums, missing_tracks = calculate_discography_missing(
                artist_id,
                albums if isinstance(albums, list) else [],
                plex_items,
            )
            await self._download_missing_tracks(missing_tracks, artist_name)
            self._set_status(job_id, "done")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Failed to process discography job %s: %s", job_id, exc)
            self._set_status(job_id, "failed")

    def _set_status(self, job_id: int, status: str) -> Optional[DiscographyJob]:
        with session_scope() as session:
            job = session.get(DiscographyJob, int(job_id))
            if job is None:
                return None
            job.status = status
            return job

    async def _fetch_existing_tracks(self, artist_name: str) -> List[Dict[str, Any]]:
        if not artist_name or self._plex is None:
            return []
        getter = getattr(self._plex, "get_artist_tracks", None)
        if getter is None:
            return []
        result = getter(artist_name)
        if asyncio.iscoroutine(result):
            return await result
        return list(result or [])

    async def _download_missing_tracks(
        self,
        missing_tracks: Iterable[Dict[str, Any]],
        artist_name: str,
    ) -> None:
        for entry in missing_tracks:
            if not isinstance(entry, dict):
                continue
            album = entry.get("album") if isinstance(entry.get("album"), dict) else {}
            track = entry.get("track") if isinstance(entry.get("track"), dict) else {}
            query = self._build_search_query(artist_name, album, track)
            if not query:
                continue
            result = await self._soulseek.search(query)
            username, file_info = self._select_download_candidate(result)
            if not username or not file_info:
                logger.warning("No Soulseek matches found for query %s", query)
                continue
            await self._soulseek.download({"username": username, "files": [file_info]})
            self._import_with_beets(file_info)
            await self._maybe_embed_artwork(file_info, album, track)
            await self._maybe_generate_lyrics(file_info, artist_name, album, track)

    @staticmethod
    def _build_search_query(
        artist_name: str,
        album: Dict[str, Any],
        track: Dict[str, Any],
    ) -> str:
        title = track.get("name") or track.get("title")
        if not title:
            return ""
        artist = artist_name or ""
        if not artist:
            artists = track.get("artists")
            if isinstance(artists, list) and artists:
                first = artists[0]
                if isinstance(first, dict):
                    artist = first.get("name", "")
        parts = [artist.strip(), title.strip()]
        if album.get("name"):
            parts.append(str(album.get("name")).strip())
        return " ".join(part for part in parts if part)

    @staticmethod
    def _select_download_candidate(
        result: Any,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        if isinstance(result, dict):
            candidates = result.get("results")
            if isinstance(candidates, list):
                for candidate in candidates:
                    username, file_info = DiscographyWorker._extract_candidate(candidate)
                    if username and file_info:
                        return username, file_info
        elif isinstance(result, list):
            for candidate in result:
                username, file_info = DiscographyWorker._extract_candidate(candidate)
                if username and file_info:
                    return username, file_info
        return None, None

    @staticmethod
    def _extract_candidate(candidate: Any) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        if not isinstance(candidate, dict):
            return None, None
        username = candidate.get("username")
        files = candidate.get("files")
        if isinstance(files, list):
            for file_info in files:
                if isinstance(file_info, dict):
                    enriched = dict(file_info)
                    if "filename" not in enriched and "name" in enriched:
                        enriched["filename"] = enriched["name"]
                    return username, enriched
        return None, None

    def _import_with_beets(self, file_info: Dict[str, Any]) -> None:
        if self._beets is None:
            return
        importer = getattr(self._beets, "import_file", None)
        if importer is None:
            return
        filename = file_info.get("local_path") or file_info.get("path") or file_info.get("filename")
        if not filename:
            return
        try:
            importer(str(filename), quiet=True)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Beets import failed for %s: %s", filename, exc)

    async def _maybe_generate_lyrics(
        self,
        file_info: Dict[str, Any],
        artist_name: str,
        album: Dict[str, Any],
        track: Dict[str, Any],
    ) -> None:
        if self._lyrics is None:
            return

        file_path = (
            file_info.get("local_path") or file_info.get("path") or file_info.get("filename")
        )
        if not file_path:
            return

        download_identifier: Optional[int]
        try:
            identifier = file_info.get("download_id")
            download_identifier = int(identifier) if identifier is not None else None
        except (TypeError, ValueError):  # pragma: no cover - defensive conversion
            download_identifier = None

        track_info: Dict[str, Any] = {}
        title = track.get("name") or track.get("title")
        if isinstance(title, str) and title.strip():
            track_info["title"] = title.strip()

        artist = artist_name
        if not artist:
            artists = track.get("artists")
            if isinstance(artists, list) and artists:
                first = artists[0]
                if isinstance(first, dict):
                    artist = str(first.get("name") or "").strip()
                else:
                    artist = str(first).strip()
            elif isinstance(track.get("artist"), str):
                artist = track.get("artist", "")
        if artist:
            track_info["artist"] = artist

        if isinstance(album, dict):
            album_name = album.get("name")
            if isinstance(album_name, str) and album_name.strip():
                track_info["album"] = album_name.strip()

        duration = track.get("duration_ms") or track.get("duration") or track.get("durationMs")
        if duration is not None:
            track_info["duration"] = duration

        spotify_track_id = track.get("id") or track.get("spotify_id")
        if isinstance(spotify_track_id, str) and spotify_track_id.strip():
            track_info["spotify_track_id"] = spotify_track_id.strip()

        try:
            await self._lyrics.enqueue(download_identifier, str(file_path), track_info)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Unable to schedule lyrics for discography download: %s", exc)

    async def _maybe_embed_artwork(
        self,
        file_info: Dict[str, Any],
        album: Dict[str, Any],
        track: Dict[str, Any],
    ) -> None:
        if self._artwork is None:
            return

        file_path = (
            file_info.get("local_path") or file_info.get("path") or file_info.get("filename")
        )
        if not file_path:
            return

        download_identifier: Optional[int]
        try:
            identifier = file_info.get("download_id")
            download_identifier = int(identifier) if identifier is not None else None
        except (TypeError, ValueError):  # pragma: no cover - defensive conversion
            download_identifier = None

        metadata: Dict[str, Any] = {}
        spotify_album_id = None
        if isinstance(album, dict):
            metadata["album"] = dict(album)
            images = album.get("images")
            if isinstance(images, list):
                metadata.setdefault("artwork_urls", []).extend(images)
            candidate = album.get("id") or album.get("spotify_id") or album.get("spotifyId")
            if isinstance(candidate, str) and candidate.strip():
                spotify_album_id = candidate.strip()

        artwork_url = None
        if isinstance(track, dict):
            artwork_url = track.get("albumArt") or track.get("artwork_url")
            if isinstance(artwork_url, dict):
                metadata.setdefault("artwork_urls", []).append(artwork_url)

        spotify_track_id = None
        if isinstance(track, dict):
            candidate = track.get("id") or track.get("spotify_id")
            if isinstance(candidate, str) and candidate.strip():
                spotify_track_id = candidate.strip()

        try:
            await self._artwork.enqueue(
                download_identifier,
                str(file_path),
                metadata=metadata,
                spotify_track_id=spotify_track_id,
                spotify_album_id=spotify_album_id,
                artwork_url=artwork_url if isinstance(artwork_url, str) else None,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Unable to schedule artwork embedding: %s", exc)
