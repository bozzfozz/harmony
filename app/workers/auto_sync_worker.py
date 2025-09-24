"""Worker that reconciles Spotify data with Plex and downloads missing tracks."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, Iterator, List, MutableMapping, Sequence

from sqlalchemy import delete, select

from app.core.beets_client import BeetsClient
from app.core.plex_client import PlexClient
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.db import session_scope
from app.logging import get_logger
from app.models import AutoSyncSkippedTrack
from app.utils.activity import record_activity
from app.utils.settings_store import read_setting, write_setting
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat

logger = get_logger(__name__)

DEFAULT_MIN_BITRATE = 192
SKIP_THRESHOLD = 3


@dataclass(frozen=True)
class TrackInfo:
    """Minimal representation of a track used for reconciliation."""

    title: str
    artist: str
    spotify_id: str | None = None
    priority: int = 0

    def key(self) -> tuple[str, str]:
        return (self.artist.strip().lower(), self.title.strip().lower())

    def as_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {"title": self.title, "artist": self.artist}
        if self.spotify_id:
            payload["spotify_id"] = self.spotify_id
        if self.priority:
            payload["priority"] = str(self.priority)
        return payload

    def __hash__(self) -> int:  # pragma: no cover - dataclass helper
        return hash(self.key())

    def __eq__(self, other: object) -> bool:  # pragma: no cover - dataclass helper
        if not isinstance(other, TrackInfo):
            return NotImplemented
        return self.key() == other.key()

    def with_priority(self, priority: int) -> TrackInfo:
        if priority == self.priority:
            return self
        return TrackInfo(
            title=self.title,
            artist=self.artist,
            spotify_id=self.spotify_id,
            priority=priority,
        )


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
        preferences_loader: Callable[[], Dict[str, bool]] | None = None,
        skip_threshold: int = SKIP_THRESHOLD,
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
        self._preferences_loader = preferences_loader
        self._skip_threshold = skip_threshold
        self._in_progress = False

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
        write_setting("worker.autosync.last_stop", datetime.utcnow().isoformat())
        mark_worker_status("autosync", "stopped")

    async def run_once(self, *, source: str = "manual") -> None:
        await self._execute_sync(source=source)

    async def _run(self) -> None:
        logger.info("AutoSyncWorker started")
        record_worker_heartbeat("autosync")
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
            self._in_progress = True
            try:
                start_time = time.perf_counter()
                sync_sources = ["spotify", "plex", "soulseek", "beets"]
                record_activity(
                    "sync",
                    "sync_started",
                    details={"trigger": source, "sources": sync_sources},
                )
                logger.info("Auto sync started (source=%s)", source)
                write_setting("worker.autosync.last_start", datetime.utcnow().isoformat())
                self._record_heartbeat()

                phase_errors: list[dict[str, str]] = []

                def _finalise_outcome(
                    downloaded_count: int,
                    skipped_count: int,
                    failure_codes: Iterable[str],
                    *,
                    missing_count: int,
                ) -> None:
                    errors_payload: list[dict[str, str]] = [dict(item) for item in phase_errors]
                    for code in sorted(set(failure_codes)):
                        errors_payload.append({"source": "soulseek", "reason": code})
                    counters = {
                        "tracks_synced": downloaded_count,
                        "tracks_skipped": skipped_count,
                        "errors": len(errors_payload),
                    }
                    if errors_payload:
                        record_activity(
                            "sync",
                            "sync_partial",
                            details={
                                "trigger": source,
                                "sources": sync_sources,
                                "missing": missing_count,
                                "counters": counters,
                                "errors": errors_payload,
                            },
                        )
                    record_activity(
                        "sync",
                        "sync_completed",
                        details={
                            "trigger": source,
                            "sources": sync_sources,
                            "missing": missing_count,
                            "counters": counters,
                        },
                    )

                try:
                    spotify_tracks, playlist_total, saved_total = self._collect_spotify_tracks()
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.error("Failed to load Spotify data: %s", exc)
                    record_activity(
                        "sync",
                        "spotify_unavailable",
                        details={"source": source, "error": str(exc)},
                    )
                    phase_errors.append({"source": "spotify", "message": str(exc)})
                    _finalise_outcome(0, 0, [], missing_count=0)
                    return

                record_activity(
                    "sync",
                    "spotify_loaded",
                    details={
                        "trigger": source,
                        "playlists": playlist_total,
                        "tracks": len(spotify_tracks),
                        "saved_tracks": saved_total,
                    },
                )
                self._record_heartbeat()

                try:
                    plex_tracks = await self._collect_plex_tracks()
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.error("Failed to inspect Plex library: %s", exc)
                    record_activity(
                        "sync",
                        "plex_unavailable",
                        details={"source": source, "error": str(exc)},
                    )
                    phase_errors.append({"source": "plex", "message": str(exc)})
                    _finalise_outcome(0, 0, [], missing_count=0)
                    return

                record_activity(
                    "sync",
                    "plex_checked",
                    details={"trigger": source, "tracks": len(plex_tracks)},
                )

                missing_tracks = spotify_tracks - plex_tracks
                missing_count = len(missing_tracks)
                record_activity(
                    "sync",
                    "downloads_requested",
                    details={"trigger": source, "count": missing_count},
                )

                if not missing_tracks:
                    logger.info("Auto sync completed without missing tracks (source=%s)", source)
                    write_setting("metrics.autosync.downloaded", "0")
                    write_setting("metrics.autosync.skipped", "0")
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    write_setting("metrics.autosync.duration_ms", str(duration_ms))
                    record_activity(
                        "sync",
                        "beets_imported",
                        details={
                            "trigger": source,
                            "imported": 0,
                            "skipped": 0,
                            "errors": [],
                        },
                    )
                    _finalise_outcome(0, 0, [], missing_count=missing_count)
                    self._record_heartbeat()
                    return

                downloaded, skipped, failures = await self._download_missing_tracks(
                    missing_tracks, source
                )

                if downloaded:
                    try:
                        await self._retry(self._plex.get_library_statistics)
                        record_activity(
                            "sync", "plex_updated", details={"source": source}
                        )
                    except Exception as exc:  # pragma: no cover - defensive logging
                        logger.error("Failed to refresh Plex statistics: %s", exc)
                        record_activity(
                            "sync",
                            "plex_update_failed",
                            details={"source": source, "error": str(exc)},
                        )
                        phase_errors.append({"source": "plex", "message": f"update_failed: {exc}"})

                record_activity(
                    "sync",
                    "beets_imported",
                    details={
                        "trigger": source,
                        "imported": len(downloaded),
                        "skipped": len(skipped),
                        "errors": sorted(failures),
                    },
                )
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                write_setting("metrics.autosync.downloaded", str(len(downloaded)))
                write_setting("metrics.autosync.skipped", str(len(skipped)))
                write_setting("metrics.autosync.duration_ms", str(duration_ms))
                _finalise_outcome(
                    len(downloaded),
                    len(skipped),
                    failures,
                    missing_count=missing_count,
                )
                self._record_heartbeat()
                logger.info(
                    "Auto sync finished (source=%s, downloaded=%d, skipped=%d, failures=%s)",
                    source,
                    len(downloaded),
                    len(skipped),
                    ",".join(sorted(failures)) or "none",
                )
    
            finally:
                self._in_progress = False

    def _collect_spotify_tracks(self) -> tuple[set[TrackInfo], int, int]:
        tracks: dict[tuple[str, str], TrackInfo] = {}
        playlist_total = 0
        saved_total = 0
        preferences = self._load_release_preferences()
        allow_all = not preferences
        playlist_response = self._spotify.get_user_playlists()
        for playlist in self._iter_dicts(self._extract_collection(playlist_response, "items")):
            playlist_id = str(playlist.get("id") or "")
            if not playlist_id:
                continue
            playlist_total += 1
            try:
                playlist_items = self._spotify.get_playlist_items(playlist_id)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to load Spotify playlist %s: %s", playlist_id, exc
                )
                continue
            for item in self._iter_dicts(self._extract_collection(playlist_items, "items")):
                track_payload = item.get("track") or item
                if not self._is_release_selected(track_payload, preferences, allow_all):
                    continue
                priority = self._calculate_track_priority(track_payload, base_priority=10)
                track_info = self._normalise_spotify_track(track_payload, priority=priority)
                if track_info:
                    key = track_info.key()
                    existing = tracks.get(key)
                    if existing is None or track_info.priority > existing.priority:
                        tracks[key] = track_info

        saved_tracks = self._spotify.get_saved_tracks()
        for item in self._iter_dicts(self._extract_collection(saved_tracks, "items")):
            track_payload = item.get("track") or item
            if not self._is_release_selected(track_payload, preferences, allow_all):
                continue
            priority = self._calculate_track_priority(track_payload, base_priority=20)
            track_info = self._normalise_spotify_track(track_payload, priority=priority)
            if track_info:
                saved_total += 1
                key = track_info.key()
                existing = tracks.get(key)
                if existing is None or track_info.priority > existing.priority:
                    tracks[key] = track_info

        return set(tracks.values()), playlist_total, saved_total

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
    ) -> tuple[list[tuple[TrackInfo, str]], list[TrackInfo], set[str]]:
        downloaded: list[tuple[TrackInfo, str]] = []
        skipped: list[TrackInfo] = []
        failure_reasons: set[str] = set()
        min_bitrate, preferred_formats = self._load_quality_rules()
        ordered: Sequence[TrackInfo] = sorted(
            set(missing),
            key=lambda item: (-item.priority, item.artist.lower(), item.title.lower()),
        )

        for track in ordered:
            if self._should_skip_track(track):
                record_activity(
                    "sync",
                    "soulseek_skipped",
                    details={"source": source, "track": track.as_dict(), "reason": "permanent"},
                )
                skipped.append(track)
                continue

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
                failure_reasons.add("search")
                self._record_failed_track(track, "search")
                skipped.append(track)
                continue

            username, file_info, rejection = self._select_soulseek_candidate(
                search_result,
                min_bitrate=min_bitrate,
                preferred_formats=preferred_formats,
            )
            if not username or not file_info:
                reason = "quality" if rejection == "quality" else "no_results"
                failure_reasons.add(reason)
                if reason == "quality":
                    logger.info("Rejecting Soulseek candidates below %dkbps for %s", min_bitrate, query)
                    record_activity(
                        "sync",
                        "soulseek_low_quality",
                        details={"source": source, "track": track.as_dict(), "min_bitrate": min_bitrate},
                    )
                else:
                    logger.info("No Soulseek results for %s", query)
                    record_activity(
                        "sync",
                        "soulseek_no_results",
                        details={"source": source, "track": track.as_dict()},
                    )
                self._record_failed_track(track, reason)
                skipped.append(track)
                continue

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
                failure_reasons.add("download")
                self._record_failed_track(track, "download")
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
                failure_reasons.add("import")
                self._record_failed_track(track, "missing_path")
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
                failure_reasons.add("import")
                self._record_failed_track(track, "import")
                skipped.append(track)
                continue

            record_activity(
                "sync",
                "track_imported",
                details={"source": source, "track": track.as_dict(), "path": path},
            )
            self._clear_failed_track(track)
            downloaded.append((track, path))

        return downloaded, skipped, failure_reasons

    async def _import_with_beets(self, path: str) -> str:
        return await asyncio.to_thread(self._beets.import_file, path, quiet=True)

    def _load_release_preferences(self) -> Dict[str, bool]:
        if self._preferences_loader is None:
            return {}
        try:
            preferences = self._preferences_loader()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to load artist preferences: %s", exc)
            return {}
        if not isinstance(preferences, dict):
            return {}
        normalised: Dict[str, bool] = {}
        for release_id, selected in preferences.items():
            if not release_id:
                continue
            normalised[str(release_id)] = bool(selected)
        return normalised

    def _calculate_track_priority(self, payload: Any, *, base_priority: int = 0) -> int:
        priority = base_priority
        popularity = payload.get("popularity")
        try:
            popularity_score = int(popularity)
        except (TypeError, ValueError):
            popularity_score = 0
        if popularity_score:
            priority += min(10, popularity_score // 10)
        if payload.get("is_local"):
            priority += 1
        return priority

    def _load_quality_rules(self) -> tuple[int, set[str]]:
        min_bitrate = self._resolve_int_setting(
            "autosync_min_bitrate", "AUTOSYNC_MIN_BITRATE", DEFAULT_MIN_BITRATE
        )
        formats_setting = read_setting("autosync_preferred_formats")
        if formats_setting is None:
            formats_setting = os.getenv("AUTOSYNC_PREFERRED_FORMATS")
        preferred_formats = {
            fmt.strip().lower()
            for fmt in (formats_setting.split(",") if formats_setting else [])
            if fmt.strip()
        }
        return min_bitrate, preferred_formats

    def _resolve_int_setting(self, setting_key: str, env_key: str, default: int) -> int:
        value = read_setting(setting_key)
        if value is None:
            value = os.getenv(env_key)
        if value:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                parsed = default
            else:
                if parsed > 0:
                    return parsed
        return default

    def _is_release_selected(
        self, payload: Any, preferences: Dict[str, bool], allow_all: bool
    ) -> bool:
        if allow_all:
            return True
        release_id = self._extract_release_id(payload)
        if release_id is None:
            return True
        return preferences.get(release_id, False)

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

    def _extract_release_id(self, payload: Any) -> str | None:
        if not isinstance(payload, MutableMapping):
            return None
        album = payload.get("album")
        if isinstance(album, MutableMapping):
            release_id = album.get("id")
            if release_id:
                return str(release_id)
        for key in ("album_id", "release_id", "albumId", "releaseId"):
            value = payload.get(key)
            if value:
                return str(value)
        return None

    def _normalise_spotify_track(self, payload: Any, *, priority: int = 0) -> TrackInfo | None:
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
        return TrackInfo(
            title=title,
            artist=artist_name,
            spotify_id=str(spotify_id) if spotify_id else None,
            priority=priority,
        )

    def _select_soulseek_candidate(
        self,
        payload: Any,
        *,
        min_bitrate: int,
        preferred_formats: set[str],
    ) -> tuple[str | None, dict[str, Any] | None, str | None]:
        candidates = self._extract_collection(payload, "results")
        if not candidates:
            candidates = self._extract_collection(payload, None)
        preferred: list[tuple[str, dict[str, Any]]] = []
        fallback: list[tuple[str, dict[str, Any]]] = []
        rejected_for_quality = False
        for entry in self._iter_dicts(candidates):
            username = entry.get("username") or entry.get("user")
            files = entry.get("files") or entry.get("tracks") or entry.get("results")
            if isinstance(files, MutableMapping):
                files = [files]
            if not username or not isinstance(files, Iterable):
                continue
            for file_info in files:
                if not isinstance(file_info, MutableMapping):
                    continue
                if not self._is_quality_match(file_info, min_bitrate):
                    rejected_for_quality = True
                    continue
                candidate = (str(username), dict(file_info))
                if preferred_formats and self._is_preferred_format(file_info, preferred_formats):
                    preferred.append(candidate)
                else:
                    fallback.append(candidate)

        selected: tuple[str, dict[str, Any]] | None = None
        if preferred:
            selected = max(preferred, key=lambda item: self._candidate_score(item[1]))
        elif fallback:
            selected = max(fallback, key=lambda item: self._candidate_score(item[1]))

        if selected:
            return selected[0], selected[1], None
        if rejected_for_quality:
            return None, None, "quality"
        return None, None, None

    def _resolve_download_path(self, file_info: MutableMapping[str, Any]) -> str | None:
        for key in ("local_path", "localPath", "path", "filename"):
            value = file_info.get(key)
            if value:
                return str(value)
        return None

    def _is_quality_match(self, file_info: MutableMapping[str, Any], min_bitrate: int) -> bool:
        value = file_info.get("bitrate")
        if value is None:
            return True
        try:
            bitrate = int(value)
        except (TypeError, ValueError):
            return True
        return bitrate >= min_bitrate

    def _is_preferred_format(
        self, file_info: MutableMapping[str, Any], preferred_formats: set[str]
    ) -> bool:
        if not preferred_formats:
            return False
        format_name = self._extract_format(file_info)
        return format_name in preferred_formats

    def _extract_format(self, file_info: MutableMapping[str, Any]) -> str:
        for key in ("format", "extension", "filetype"):
            value = file_info.get(key)
            if isinstance(value, str) and value:
                return value.strip().lower()
        filename = file_info.get("filename") or file_info.get("path")
        if isinstance(filename, str) and "." in filename:
            return os.path.splitext(filename)[1].replace(".", "").lower()
        return ""

    def _candidate_score(self, file_info: MutableMapping[str, Any]) -> tuple[int, int]:
        try:
            bitrate = int(file_info.get("bitrate", 0))
        except (TypeError, ValueError):
            bitrate = 0
        try:
            size = int(file_info.get("size", 0))
        except (TypeError, ValueError):
            size = 0
        return bitrate, size

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

    def _track_identifier(self, track: TrackInfo) -> str:
        if track.spotify_id:
            return track.spotify_id
        artist, title = track.key()
        return f"{artist}::{title}"

    def _should_skip_track(self, track: TrackInfo) -> bool:
        identifier = self._track_identifier(track)
        with session_scope() as session:
            record = session.execute(
                select(AutoSyncSkippedTrack).where(AutoSyncSkippedTrack.track_key == identifier)
            ).scalar_one_or_none()
            if record is None:
                return False
            return record.failure_count >= self._skip_threshold

    def _record_failed_track(self, track: TrackInfo, reason: str) -> None:
        identifier = self._track_identifier(track)
        now = datetime.utcnow()
        with session_scope() as session:
            record = session.execute(
                select(AutoSyncSkippedTrack).where(AutoSyncSkippedTrack.track_key == identifier)
            ).scalar_one_or_none()
            if record is None:
                session.add(
                    AutoSyncSkippedTrack(
                        track_key=identifier,
                        spotify_id=track.spotify_id,
                        failure_reason=reason,
                        failure_count=1,
                        last_attempt_at=now,
                    )
                )
            else:
                record.failure_reason = reason
                record.failure_count += 1
                record.last_attempt_at = now

    def _clear_failed_track(self, track: TrackInfo) -> None:
        identifier = self._track_identifier(track)
        with session_scope() as session:
            session.execute(
                delete(AutoSyncSkippedTrack).where(AutoSyncSkippedTrack.track_key == identifier)
            )

    def _record_heartbeat(self) -> None:
        record_worker_heartbeat("autosync")

