# Changelog

## v1.x.x

- Smart Search – `/api/search` akzeptiert optionale Filter für Genre, Jahr und Audioqualität. Die Ergebnisse werden als einheitliche Trefferliste mit Quelle, Typ, Jahr und Qualitätslabel zurückgegeben. Fehler einzelner Dienste tauchen weiterhin separat im `errors`-Block auf.
- High-Quality Artwork – Downloads enthalten automatisch eingebettete Cover in Originalauflösung. Artwork-Dateien werden pro `spotify_album_id` zwischengespeichert (konfigurierbar via `ARTWORK_DIR`) und beim Abschluss von Downloads in MP3/FLAC/MP4 eingebettet. Neue API-Endpunkte: `GET /soulseek/download/{id}/artwork` (liefert Bild oder `404`) und `POST /soulseek/download/{id}/artwork/refresh` (erneut einreihen). Download-Datensätze speichern die zugehörigen Spotify-IDs (`spotify_track_id`, `spotify_album_id`).
- Rich Metadata – alle Downloads enthalten zusätzliche Tags (Genre, Komponist, Produzent, ISRC, Copyright), werden direkt in die Dateien geschrieben und lassen sich per `GET /soulseek/download/{id}/metadata` abrufen oder über `POST /soulseek/download/{id}/metadata/refresh` neu befüllen.
- Complete Discographies – gesamte Künstlerdiskografien können automatisch heruntergeladen und kategorisiert werden.
- Automatic Lyrics – Downloads enthalten jetzt synchronisierte `.lrc`-Dateien mit Songtexten aus der Spotify-API (Fallback Musixmatch/lyrics.ovh) samt neuen Endpunkten zum Abruf und Refresh.
