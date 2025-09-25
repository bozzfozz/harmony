# Changelog

## v1.x.x

- High-Quality Artwork – Downloads enthalten automatisch eingebettete Cover in Originalauflösung. Artwork-Dateien werden pro `spotify_album_id` zwischengespeichert (konfigurierbar via `ARTWORK_DIR`) und beim Abschluss von Downloads in MP3/FLAC/MP4 eingebettet. Neue API-Endpunkte: `GET /soulseek/download/{id}/artwork` (liefert Bild oder `404`) und `POST /soulseek/download/{id}/artwork/refresh` (erneut einreihen). Download-Datensätze speichern die zugehörigen Spotify-IDs (`spotify_track_id`, `spotify_album_id`).
- Rich Metadata – alle Downloads enthalten zusätzliche Tags (Genre, Komponist, Produzent, ISRC, Copyright) und können per `GET /soulseek/download/{id}/metadata` abgerufen werden.
- Complete Discographies – gesamte Künstlerdiskografien können automatisch heruntergeladen und kategorisiert werden.
- Automatic Lyrics – Downloads enthalten jetzt synchronisierte `.lrc`-Dateien mit Songtexten aus der Spotify-API (Fallback Musixmatch/lyrics.ovh) samt neuen Endpunkten zum Abruf und Refresh.
