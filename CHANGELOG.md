# Changelog

## v1.x.x

- High-Quality Artwork – Downloads enthalten automatisch eingebettete Cover in Originalauflösung, gespeichert unter `/artwork/` inklusive neuem Refresh-Endpoint `POST /soulseek/download/{id}/artwork/refresh`.
- Rich Metadata – alle Downloads enthalten zusätzliche Tags (Genre, Komponist, Produzent, ISRC, Copyright) und können per `GET /soulseek/download/{id}/metadata` abgerufen werden.
- Complete Discographies – gesamte Künstlerdiskografien können automatisch heruntergeladen und kategorisiert werden.
- Automatic Lyrics – Downloads enthalten jetzt synchronisierte `.lrc`-Dateien mit Songtexten aus der Spotify-API (Fallback Musixmatch/lyrics.ovh) samt neuen Endpunkten zum Abruf und Refresh.
