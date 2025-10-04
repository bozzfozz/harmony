# API-Referenz (MVP-Slim)

Diese Datei beschreibt die aktiven REST-Endpunkte des Harmony-Backends im Spotify/Soulseek-MVP. Legacy-Routen für Plex/Beets sind deaktiviert und werden in der OpenAPI-Spezifikation nicht mehr generiert. Der entsprechende Code liegt unter [`archive/integrations/plex_beets/`](../archive/integrations/plex_beets/).

Alle Endpunkte folgen dem Schema `https://<host>/api/v1/<route>` und liefern JSON, sofern nicht anders angegeben. Der Basispräfix kann über die Umgebungsvariable `API_BASE_PATH` angepasst werden.

## Authentifizierung

- Alle produktiven Endpunkte erfordern einen gültigen API-Key im Header `X-API-Key`. Alternativ wird `Authorization: Bearer <key>` akzeptiert.
- Die Liste gültiger Schlüssel wird über `HARMONY_API_KEYS` (kommagetrennt) oder `HARMONY_API_KEYS_FILE` gepflegt. Mehrere Schlüssel können parallel aktiv bleiben.
- Öffentliche Routen (z. B. `/api/v1/health`) lassen sich via `AUTH_ALLOWLIST` freischalten. Die Angabe erfolgt als kommagetrennte Pfadpräfix-Liste inklusive Versionierung.
- CORS ist standardmäßig restriktiv (`ALLOWED_ORIGINS`). Für Tests und lokale Entwicklung kann `HARMONY_DISABLE_WORKERS=1` gesetzt werden, um Hintergrundprozesse auszuschalten.
- Spotify-Routen mit OAuth benötigen weiterhin gültige Credentials (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`).
- Soulseek-Routen verwenden slskd (`SLSKD_URL`, optional `SLSKD_API_KEY`).

## Spotify

| Methode | Route | Beschreibung |
| ------- | ----- | ------------ |
| `GET` | `/spotify/status` | Verbindungsstatus & gespeicherte Credentials. |
| `GET` | `/spotify/search/tracks` | Suche nach Tracks via `query`-Parameter (OAuth erforderlich). |
| `GET` | `/spotify/search/artists` | Suche nach Artists via `query`-Parameter (OAuth erforderlich). |
| `GET` | `/spotify/search/albums` | Suche nach Alben via `query`-Parameter (OAuth erforderlich). |
| `POST` | `/spotify/backfill/run` | Startet den Backfill-Worker für FREE-Ingest-Daten. Antwortet mit `202` und Job-ID. |
| `GET` | `/spotify/backfill/jobs/{id}` | Liefert Fortschritt/Statistiken eines Backfill-Jobs. |
| `POST` | `/spotify/import/free` | Parserbasierte Ingest-API (Links/Tracklisten). |
| `POST` | `/spotify/import/free/upload` | Datei-Upload (CSV/TXT/JSON) für Free-Ingest. |
| `GET` | `/spotify/import/jobs/{id}` | Status eines Free-Ingest-Jobs. |
| `POST` | `/spotify/mode` | Wechselt zwischen FREE und PRO. |
| `GET` | `/spotify/mode` | Aktueller Modus. |

## Soulseek

| Methode | Route | Beschreibung |
| ------- | ----- | ------------ |
| `GET` | `/soulseek/status` | Status des slskd-Daemons inkl. Queue-Informationen. |
| `POST` | `/soulseek/search` | Suche nach Dateien/Nutzern. |
| `POST` | `/soulseek/download` | Erstellt einen neuen Downloadjob. |
| `GET` | `/soulseek/downloads` | Liste aller Downloads inkl. Status/Retry-Infos. |
| `GET` | `/soulseek/download/{id}` | Einzelner Downloaddatensatz. |
| `DELETE` | `/soulseek/download/{id}` | Bricht einen Download ab. |
| `POST` | `/soulseek/download/{id}/requeue` | Plant fehlgeschlagene Downloads erneut ein. |
| `GET` | `/soulseek/download/{id}/artwork` | Liefert eingebettetes Artwork (`image/jpeg`). |
| `POST` | `/soulseek/download/{id}/artwork/refresh` | Erzwingt Artwork-Refresh. |
| `GET` | `/soulseek/download/{id}/lyrics` | Gibt generierte `.lrc`-Datei zurück. |
| `POST` | `/soulseek/download/{id}/lyrics/refresh` | Erzwingt Lyrics-Refresh. |

## Suche & Matching

| Methode | Route | Beschreibung |
| ------- | ----- | ------------ |
| `POST` | `/search` | Aggregierte Suche über Spotify & Soulseek. Unterstützt Filter (`types`, `genres`, `year_range`, `duration_ms`, `explicit`, `min_bitrate`, `preferred_formats`, `username`). |
| `POST` | `/matching/spotify-to-soulseek` | Bewertet Spotify-Track vs. Soulseek-Kandidaten, persistiert das Ergebnis. |
| `POST` | `/matching/spotify-to-soulseek/preview` | Liefert nur berechneten Score ohne Persistenz. |
| `GET` | `/matching/jobs` | Queue-Status des Matching-Workers. |
| `POST` | `/matching/spotify-to-plex` | **Legacy** – antwortet mit `404`. |
| `POST` | `/matching/spotify-to-plex-album` | **Legacy** – antwortet mit `404`. |
| `POST` | `/matching/discography/plex` | **Legacy** – antwortet mit `404`. |

## Metadata & Watchlist

| Methode | Route | Beschreibung |
| ------- | ----- | ------------ |
| `GET` | `/soulseek/download/{id}/metadata` | Liefert angereicherte Metadaten. |
| `POST` | `/soulseek/download/{id}/metadata/refresh` | Erstellt einen neuen Metadaten-Job (Spotify-Quelle). |
| `POST` | `/metadata/update` | Antwortet mit `503`, solange Plex/Beets archiviert bleiben. |
| `POST` | `/metadata/stop` | Ebenfalls `503` – nur als Legacy-Platzhalter. |
| `GET` | `/metadata/status` | Liefert `503` und verweist auf deaktivierte Legacy-Pfade. |
| `POST` | `/watchlist` | Fügt Artist zur Watchlist hinzu. |
| `GET` | `/watchlist` | Listet alle Watchlist-Einträge. |
| `DELETE` | `/watchlist/{id}` | Entfernt Eintrag (`{id}` = interne Watchlist-ID). |

## Settings & System

| Methode | Route | Beschreibung |
| ------- | ----- | ------------ |
| `GET` | `/settings` | Liste gespeicherter Key-Value Settings. |
| `POST` | `/settings` | Setzt/aktualisiert einen Setting-Wert. |
| `GET` | `/settings/history` | Versionsverlauf der letzten Änderungen. |
| `GET` | `/status` | Dashboard-Daten (Version, Uptime, Worker-/Connection-Status). |
| `GET` | `/system/stats` | Systemmetriken (CPU, RAM, Disk). |
| `GET` | `/integrations` | Liste aktiver Provider inkl. Health-Status. |

## Health & Activity

| Methode | Route | Beschreibung |
| ------- | ----- | ------------ |
| `GET` | `/health/spotify` | Prüft Spotify-Credentials und optional fehlende Felder. |
| `GET` | `/health/soulseek` | Prüft slskd-Erreichbarkeit. |
| `GET` | `/activity` | Liefert Activity-Feed (Sync-, Watchlist-, Download-Events). |

## OpenAPI

`tests/snapshots/openapi.json` enthält einen Snapshot der generierten OpenAPI-Spezifikation. Die CI validiert Änderungen automatisch (`python -m app.main` → `app.openapi()`).

## HTTP-Caching

- Alle idempotenten `GET`-Antworten tragen nun `ETag`, `Last-Modified`, `Cache-Control` und `Vary`-Header. Clients können `If-None-Match`
  oder `If-Modified-Since` senden, um `304 Not Modified` ohne Body zu erhalten.
- Serverseitig puffert ein In-Memory-LRU-Cache (`ResponseCache`) erfolgreiche `GET`-Antworten unter Berücksichtigung von Query-Params,
  Pfadparametern und Authentifizierungsvarianten. Schreiboperationen (`POST/PUT/PATCH/DELETE`) invalidieren die entsprechenden Schlüssel.
- Feature-Flags & Konfiguration:

| Variable | Default | Beschreibung |
| -------- | ------- | ------------ |
| `CACHE_ENABLED` | `true` | Aktiviert Middleware & Cache. |
| `CACHE_DEFAULT_TTL_S` | `30` | TTL (Sekunden) für ungepolicte Routen. |
| `CACHE_STALE_WHILE_REVALIDATE_S` | `60` | `stale-while-revalidate`-Fenster (Sekunden). |
| `CACHE_MAX_ITEMS` | `5000` | Maximal zwischengespeicherte Einträge (LRU). |
| `CACHE_STRATEGY_ETAG` | `strong` | `strong` oder `weak` ETag-Generierung. |
| `CACHEABLE_PATHS` | – | Optionale CSV-Liste `</pfad>|<ttl>|<swr>` pro Route; leer ⇒ alle GET-Routen unter `/api/v1`. |
| `CACHE_FAIL_OPEN` | `true` | Bei Cache-Fehlern Antwort ohne Cache ausliefern. |

- Monitoring: Strukturierte Logs (`event=cache.hit|miss|store|invalidate`) zeigen Keys, TTLs und Latenzen an. Zusätzliche Metriken lassen sich
  via Observability-Pipeline ableiten.

## Archivierte Routen

Alle `/plex/*` und `/beets/*`-Routen sind aus der App entfernt und liefern `404` bzw. sind vollständig deaktiviert. Das Audit-Skript verhindert, dass neue Referenzen im aktiven Code auftauchen.
