# Changelog

## v1.x.x

- High-Quality Artwork – eigener Worker lädt Albumcover in maximaler Auflösung, bettet sie in Audiodateien ein und stellt den Endpoint `GET /soulseek/download/{id}/artwork` bereit.
- Rich Metadata – alle Downloads enthalten zusätzliche Tags (Genre, Komponist, Produzent, ISRC, Copyright) und können per `GET /soulseek/download/{id}/metadata` abgerufen werden.
- Complete Discographies – gesamte Künstlerdiskografien können automatisch heruntergeladen und kategorisiert werden.
- Automatic Lyrics – alle neuen Downloads enthalten synchronisierte Lyrics (.lrc).
