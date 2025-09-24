"""Worker that reconciles Spotify data with Plex and downloads missing tracks."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, List, MutableMapping, Sequence

from app.core.beets_client import BeetsClient
from app.core.plex_client import PlexClient
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.logging import get_logger
from app.utils.activity import record_activity

logger = get_logger(__name__)


@dataclass(frozen=True)
class TrackInfo:
    """Minimal representation of a track used for reconciliation."""

    title: str
    artist: str
    spotify_id: str | None = None

    def key(self) -> tuple[str, str]:
        return (self.artist.strip().lower(), self.title.strip().lower())

    def as_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {"title": self.title, "artist": self.artist}
        if self.spotify_id:
            payload["spotify_id"] = self.spotify_id
        return payload

    def __hash__(self) -> int:  # pragma: no cover - dataclass helper
        return hash(self.key())

    def __eq__(self, other: object) -> bool:  # pragma: no cover - dataclass helper
        if not isinstance(other, TrackInfo):
            return NotImplemented
        return self.key() == other.key()


class AutoSyncWorker:
    """Synchronise Spotify data with Plex and trigger downloads/imports when needed."""

    def __init__(
        self,
        spotify_client: SpotifyClient,
        plex_client: PlexClient,
        soulseek_client: SoulseekClient,
        beets_client: BeetsClient,
        *,
        interval_seconds: float = 86_400.0,
        retry_attempts: int = 3,
        retry_delay: float = 1.5,
    ) -> None:
        self._spotify = spotify_client
        self._plex = plex_client
        self._soulseek = soulseek_client
        self._beets = beets_client
        self._interval = interval_seconds
        self._retry_attempts = retry_attempts
        self._retry_delay = retry_delay
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._task is not None:
            try:
                await self._task
            finally:
                self._task = None

    async def run_once(self, *, source: str = "manual") -> None:
        await self._execute_sync(source=source)

    async def _run(self) -> None:
        logger.info("AutoSyncWorker started")
        try:
            while self._running:
                await self._execute_sync(source="scheduled")
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:  # pragma: no cover - defensive lifecycle handling
            logger.debug("AutoSyncWorker cancelled")
            raise
        finally:
            self._running = False
            logger.info("AutoSyncWorker stopped")

    async def _execute_sync(self, *, source: str) -> None:
        async with self._lock:
            record_activity("sync", "autosync_started", details={"source": source})
            logger.info("Auto sync started (source=%s)", source)

            try:
                spotify_tracks = self._collect_spotify_tracks()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Failed to load Spotify data: %s", exc)
                record_activity(
                    "sync",
                    "spotify_unavailable",
                    details={"source": source, "error": str(exc)},
                )
                record_activity(
                    "sync", "partial", details={"source": source, "reason": "spotify"}
                )
                return

            record_activity(
                "sync",
                "spotify_loaded",
                details={"source": source, "tracks": len(spotify_tracks)},
            )

            try:
                plex_tracks = await self._collect_plex_tracks()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Failed to inspect Plex library: %s", exc)
                record_activity(
                    "sync",
                    "plex_unavailable",
                    details={"source": source, "error": str(exc)},
                )
                record_activity(
                    "sync", "partial", details={"source": source, "reason": "plex"}
                )
                return

            record_activity(
                "sync",
                "plex_loaded",
                details={"source": source, "tracks": len(plex_tracks)},
            )

            missing_tracks = spotify_tracks - plex_tracks
            record_activity(
                "sync",
                "comparison_complete",
                details={"source": source, "missing": len(missing_tracks)},
            )

            if not missing_tracks:
                logger.info("Auto sync completed without missing tracks (source=%s)", source)
                record_activity("sync", "completed", details={"source": source, "missing": 0})
                return

            record_activity(
                "sync",
                "downloads_requested",
                details={"source": source, "count": len(missing_tracks)},
            )

            downloaded, skipped = await self._download_missing_tracks(missing_tracks, source)

            if downloaded:
                try:
                    await self._retry(self._plex.get_library_statistics)
                    record_activity("sync", "plex_updated", details={"source": source})
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.error("Failed to refresh Plex statistics: %s", exc)
                    record_activity(
                        "sync",
                        "plex_update_failed",
                        details={"source": source, "error": str(exc)},
                    )

            status = "completed" if not skipped else "partial"
            record_activity(
                "sync",
                status,
                details={
                    "source": source,
                    "downloaded": len(downloaded),
                    "skipped": len(skipped),
                },
            )
            logger.info(
                "Auto sync finished (source=%s, downloaded=%d, skipped=%d)",
                source,
                len(downloaded),
                len(skipped),
            )

    def _collect_spotify_tracks(self) -> set[TrackInfo]:
        tracks: set[TrackInfo] = set()
        playlist_response = self._spotify.get_user_playlists()
        for playlist in self._iter_dicts(self._extract_collection(playlist_response, "items")):
            playlist_id = str(playlist.get("id") or "")
            if not playlist_id:
                continue
            try:
                playlist_items = self._spotify.get_playlist_items(playlist_id)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to load Spotify playlist %s: %s", playlist_id, exc
                )
                continue
            for item in self._iter_dicts(self._extract_collection(playlist_items, "items")):
                track_info = self._normalise_spotify_track(item.get("track") or item)
                if track_info:
                    tracks.add(track_info)

        saved_tracks = self._spotify.get_saved_tracks()
        for item in self._iter_dicts(self._extract_collection(saved_tracks, "items")):
            track_info = self._normalise_spotify_track(item.get("track") or item)
            if track_info:
                tracks.add(track_info)

        return tracks

    async def _collect_plex_tracks(self) -> set[TrackInfo]:
        tracks: set[TrackInfo] = set()
        libraries = await self._retry(self._plex.get_libraries)
        container = libraries.get("MediaContainer", {}) if isinstance(libraries, dict) else {}
        sections = container.get("Directory", []) if isinstance(container, MutableMapping) else []

        for section in sections or []:
            if not isinstance(section, MutableMapping):
                continue
            if str(section.get("type")) not in {"artist", "music"}:
                continue
            section_id = section.get("key")
            if not section_id:
                continue
            try:
                payload = await self._retry(
                    self._plex.get_library_items, str(section_id), {"type": "10"}
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to load Plex section %s items: %s", section_id, exc
                )
                continue
            container_payload = (
                payload.get("MediaContainer", {}) if isinstance(payload, dict) else {}
            )
            metadata = container_payload.get("Metadata", [])
            for entry in metadata or []:
                if not isinstance(entry, MutableMapping):
                    continue
                title = str(entry.get("title") or "").strip()
                artist = (
                    entry.get("grandparentTitle")
                    or entry.get("parentTitle")
                    or entry.get("artist")
                    or ""
                )
                artist = str(artist).strip()
                if not title or not artist:
                    continue
                tracks.add(TrackInfo(title=title, artist=artist))
        return tracks

    async def _download_missing_tracks(
        self, missing: Iterable[TrackInfo], source: str
    ) -> tuple[list[tuple[TrackInfo, str]], list[TrackInfo]]:
        downloaded: list[tuple[TrackInfo, str]] = []
        skipped: list[TrackInfo] = []
        ordered: Sequence[TrackInfo] = sorted(
            set(missing), key=lambda item: (item.artist.lower(), item.title.lower())
        )

        for track in ordered:
            query = f"{track.artist} {track.title}".strip()
            try:
                search_result = await self._retry(self._soulseek.search, query)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Soulseek search failed for %s: %s", query, exc)
                record_activity(
                    "sync",
                    "soulseek_error",
                    details={"source": source, "track": track.as_dict(), "error": str(exc)},
                )
                skipped.append(track)
                continue

            candidate = self._select_soulseek_candidate(search_result)
            if candidate is None:
                logger.info("No Soulseek results for %s", query)
                record_activity(
                    "sync",
                    "soulseek_no_results",
                    details={"source": source, "track": track.as_dict()},
                )
                skipped.append(track)
                continue

            username, file_info = candidate
            try:
                await self._retry(
                    self._soulseek.download,
                    {"username": username, "files": [file_info]},
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Soulseek download failed for %s: %s", query, exc)
                record_activity(
                    "sync",
                    "download_failed",
                    details={"source": source, "track": track.as_dict(), "error": str(exc)},
                )
                skipped.append(track)
                continue

            record_activity(
                "sync",
                "download_enqueued",
                details={"source": source, "track": track.as_dict(), "username": username},
            )

            path = self._resolve_download_path(file_info)
            if not path:
                logger.warning("Missing download path for %s", track)
                record_activity(
                    "sync",
                    "import_failed",
                    details={
                        "source": source,
                        "track": track.as_dict(),
                        "error": "missing_path",
                    },
                )
                skipped.append(track)
                continue

            try:
                await self._retry(self._import_with_beets, path)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Beets import failed for %s: %s", path, exc)
                record_activity(
                    "sync",
                    "import_failed",
                    details={"source": source, "track": track.as_dict(), "error": str(exc)},
                )
                skipped.append(track)
                continue

            record_activity(
                "sync",
                "track_imported",
                details={"source": source, "track": track.as_dict(), "path": path},
            )
            downloaded.append((track, path))

        return downloaded, skipped

    async def _import_with_beets(self, path: str) -> str:
        return await asyncio.to_thread(self._beets.import_file, path, quiet=True)

    def _extract_collection(self, payload: Any, key: str | None = None) -> List[Any]:
        if isinstance(payload, list):
            return [item for item in payload if item is not None]
        if isinstance(payload, MutableMapping):
            value = payload if key is None else payload.get(key)
            if isinstance(value, list):
                return [item for item in value if item is not None]
            if value is not None:
                return [value]
        return []

    def _iter_dicts(self, items: Iterable[Any]) -> Iterator[MutableMapping[str, Any]]:
        for item in items:
            if isinstance(item, MutableMapping):
                yield item

    def _normalise_spotify_track(self, payload: Any) -> TrackInfo | None:
        if not isinstance(payload, MutableMapping):
            return None
        title = str(payload.get("name") or "").strip()
        if not title:
            return None
        artists = payload.get("artists")
        artist_name = ""
        if isinstance(artists, Sequence) and not isinstance(artists, (str, bytes)):
            for artist in artists:
                if isinstance(artist, MutableMapping):
                    artist_name = str(artist.get("name") or "").strip()
                elif isinstance(artist, str):
                    artist_name = artist.strip()
                if artist_name:
                    break
        if not artist_name:
            artist_name = str(payload.get("artist") or "").strip()
        if not artist_name:
            return None
        spotify_id = payload.get("id")
        return TrackInfo(title=title, artist=artist_name, spotify_id=str(spotify_id) if spotify_id else None)

    def _select_soulseek_candidate(self, payload: Any) -> tuple[str, dict[str, Any]] | None:
        candidates = self._extract_collection(payload, "results")
        if not candidates:
            candidates = self._extract_collection(payload, None)
        for entry in self._iter_dicts(candidates):
            username = entry.get("username") or entry.get("user")
            files = entry.get("files") or entry.get("tracks") or entry.get("results")
            if isinstance(files, MutableMapping):
                files = [files]
            if not username or not isinstance(files, Iterable):
                continue
            for file_info in files:
                if isinstance(file_info, MutableMapping):
                    return str(username), dict(file_info)
        return None

    def _resolve_download_path(self, file_info: MutableMapping[str, Any]) -> str | None:
        for key in ("local_path", "localPath", "path", "filename"):
            value = file_info.get(key)
            if value:
                return str(value)
        return None

    async def _retry(self, func, *args, attempts: int | None = None, delay: float | None = None):
        attempts = attempts or self._retry_attempts
        delay = delay or self._retry_delay
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                result = func(*args)
                if asyncio.iscoroutine(result):
                    return await result
                return result
            except Exception as exc:  # pragma: no cover - defensive logging
                last_error = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "Retrying %s (attempt %d/%d): %s",
                    getattr(func, "__name__", repr(func)),
                    attempt,
                    attempts,
                    exc,
                )
                await asyncio.sleep(delay * attempt)
        assert last_error is not None
        raise last_error

