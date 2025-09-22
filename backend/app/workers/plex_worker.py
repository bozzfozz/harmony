"""Worker responsible for synchronising Plex metadata into the database."""

from __future__ import annotations

from typing import Iterable

from app.db import SessionLocal
from app.utils.logging_config import get_logger
from backend.app.core.plex_client import PlexClient
from backend.app.models.plex_models import PlexAlbum, PlexArtist, PlexTrack

logger = get_logger("plex_worker")


class PlexWorker:
    """Synchronise Plex artists, albums and tracks into SQLite."""

    def __init__(self, client: PlexClient | None = None) -> None:
        self.client = client or PlexClient()

    def sync(self) -> None:
        """Fetch data from Plex and persist it to the database."""

        logger.info("Starting Plex metadata synchronisation")

        try:
            artists_data = self.client.get_all_artists()
        except Exception as exc:
            logger.error("Unable to fetch artists from Plex: %s", exc)
            raise

        with SessionLocal() as session:
            try:
                session.query(PlexTrack).delete(synchronize_session=False)
                session.query(PlexAlbum).delete(synchronize_session=False)
                session.query(PlexArtist).delete(synchronize_session=False)

                for artist_record in artists_data:
                    artist_id = self._normalise_identifier(artist_record.get("id"))
                    if not artist_id:
                        logger.warning("Skipping Plex artist without identifier: %s", artist_record)
                        continue

                    name = str(artist_record.get("name", ""))
                    artist = PlexArtist(id=artist_id, name=name)
                    session.add(artist)
                    logger.info("Stored Plex artist %s", artist_id)

                    albums_data = self._fetch_albums(artist_id)
                    for album_record in albums_data:
                        album_id = self._normalise_identifier(album_record.get("id"))
                        if not album_id:
                            logger.warning("Skipping Plex album without identifier: %s", album_record)
                            continue

                        title = str(album_record.get("title", ""))
                        album = PlexAlbum(id=album_id, title=title, artist_id=artist_id)
                        session.add(album)
                        logger.info("Stored Plex album %s for artist %s", album_id, artist_id)

                        tracks_data = self._fetch_tracks(album_id)
                        for track_record in tracks_data:
                            track_id = self._normalise_identifier(track_record.get("id"))
                            if not track_id:
                                logger.warning("Skipping Plex track without identifier: %s", track_record)
                                continue

                            title = str(track_record.get("title", ""))
                            duration = track_record.get("duration")
                            duration_value = int(duration) if isinstance(duration, (int, float)) else None

                            track = PlexTrack(
                                id=track_id,
                                title=title,
                                album_id=album_id,
                                duration=duration_value,
                            )
                            session.add(track)
                            logger.info("Stored Plex track %s for album %s", track_id, album_id)

                session.commit()
            except Exception:
                session.rollback()
                logger.error("Plex synchronisation failed", exc_info=True)
                raise

        logger.info("Plex metadata synchronisation finished with %s artists", len(artists_data))

    def _fetch_albums(self, artist_id: str) -> Iterable[dict[str, object]]:
        try:
            return self.client.get_albums_by_artist(artist_id)
        except Exception as exc:
            logger.error("Unable to fetch albums for artist %s: %s", artist_id, exc)
            raise

    def _fetch_tracks(self, album_id: str) -> Iterable[dict[str, object]]:
        try:
            return self.client.get_tracks_by_album(album_id)
        except Exception as exc:
            logger.error("Unable to fetch tracks for album %s: %s", album_id, exc)
            raise

    @staticmethod
    def _normalise_identifier(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
