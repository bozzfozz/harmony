# ENV- und Konfigurations-Matrix

| Variable | Default / Quelle | Wirkung | Empfehlung / Profil |
| --- | --- | --- | --- |
| `FEATURE_REQUIRE_AUTH` | Profil-Defaults aus `_SECURITY_PROFILE_DEFAULTS` (Default-/Dev-Profile `false`, Prod `true`) mit optionalem ENV-Override via `FEATURE_REQUIRE_AUTH`.【F:app/config.py†L345-L456】【F:app/config.py†L1665-L1742】 | API setzt ohne Override auf Profil-Defaults; ohne Auth greift nur die Allowlist. | **prod:** `HARMONY_PROFILE=prod` belässt `true`; nur bei Ausnahmen überschreiben und API-Keys pflegen.<br>**dev/test:** Default-/Dev-Profile liefern `false`, Override nur für Auth-Tests setzen. |
| `FEATURE_RATE_LIMITING` | Profil-Defaults aus `_SECURITY_PROFILE_DEFAULTS` (Default-/Dev-Profile `false`, Prod `true`) mit optionalem ENV-Override via `FEATURE_RATE_LIMITING`.【F:app/config.py†L345-L456】【F:app/config.py†L1665-L1742】 | Rate-Limit greift gemäß Profil oder Override; deaktiviert ⇒ Gefahr ungebremster Clients. | **prod:** `HARMONY_PROFILE=prod` nutzt `true`; Limits nur gezielt anpassen.<br>**dev:** Default-/Dev-Profile halten `false`; bei Testbedarf gezielt aktivieren. |
| `FEATURE_ENABLE_LEGACY_ROUTES` | `False`【F:app/config.py†L720-L726】 | Aktiviert Legacy-Endpunkte + Logging-Route. | Nur setzen, wenn Alt-Clients nötig; langfristig entfernen. |
| `HARMONY_DISABLE_WORKERS` | Nur wenn gesetzt (keine Defaults)【F:app/main.py†L213-L215】 | Deaktiviert alle Hintergrund-Worker beim Start. | Für lokale Tests ohne Worker nutzen; in prod unset lassen. |
| `WATCHLIST_INTERVAL` | `86400s` Default【F:app/main.py†L217-L228】 | Polling-Intervall des Watchlist-Workers. | **prod:** 86400 (1× täglich) oder kleiner für häufigere Scans.<br>**dev:** 300–600 zum Testen. |
| `WATCHLIST_MAX_CONCURRENCY` / `WATCHLIST_CONCURRENCY` | min(10, Wert, Default `3`)【F:app/config.py†L759-L771】 | Parallelität beim Abholen von Künstlern. | Prod-Wert abhängig von API-Limits; dev minimal halten. |
| `CACHE_ENABLED`, `CACHE_DEFAULT_TTL_S`, `CACHE_MAX_ITEMS`, `CACHE_STRATEGY_ETAG` | Enabled=`true`, TTL=`30s`, Items=`5000`, ETag=`strong`【F:app/main.py†L470-L505】 | Steuert ConditionalCache-Middleware (GET/HEAD). | Prod: TTL auf 60–120s erhöhen für häufige GETs; dev: optional deaktivieren. |
| `MATCH_FUZZY_MAX_CANDIDATES`, `MATCH_MIN_ARTIST_SIM`, `MATCH_COMPLETE_THRESHOLD`, `MATCH_NEARLY_THRESHOLD` | Defaults 50 / 0.6 / 0.9 / 0.8【F:app/config.py†L342-L392】【F:app/config.py†L159-L209】 | Fuzzy-Matching-Sensitivität im `MusicMatchingEngine`. | Prod: Monitoring der Scores → ggf. thresholds feinjustieren; dev/test: Defaults nutzen. |
| `SLSKD_TIMEOUT_MS`, `SLSKD_RETRY_MAX`, `SLSKD_RETRY_BACKOFF_BASE_MS`, `SLSKD_JITTER_PCT` | 8000 ms / 3 / 250 ms / 20 %【F:app/config.py†L565-L625】 | Timeout- & Retry-Strategie für Soulseek-Adapter. | Prod: An Provider-Verfügbarkeit anpassen; dev: ggf. längere Timeouts. |
| `PROVIDER_MAX_CONCURRENCY` | Default `4`【F:app/config.py†L728-L738】 | Parallele Requests je Provider im Integration-Gateway. | Prod: An Netzwerk/Rate-Limits ausrichten; dev: 1–2. |
| `INTEGRATIONS_ENABLED` | Fallback `("spotify",)`【F:app/config.py†L234-L246】【F:app/config.py†L728-L738】 | Steuert aktive Provider. | Prod: explizit pflegen (z. B. `spotify,slskd`); dev: Minimalkonfiguration. |
| `FREE_IMPORT_MAX_LINES` / `FREE_IMPORT_MAX_FILE_BYTES` / `FREE_IMPORT_MAX_PLAYLIST_LINKS` | 200 / 1 048 576 / 1 000【F:app/config.py†L520-L537】 | Grenzen für kostenlosen Playlist-Import. | Prod: Werte an Geschäftsregeln koppeln; dev: kleine Werte für Tests. |
| `WORKER_VISIBILITY_TIMEOUT_S` | Default 60s, min 5s【F:app/workers/persistence.py†L42-L47】 | Lease-Laufzeit für persistente Jobs. | Prod: 60–120s; bei langen Jobs anpassen.<br>Dev: kürzer für schnelle Tests. |
| `CACHEABLE_PATHS` | leer ⇒ nur explizite Policies greifen【F:app/main.py†L478-L486】 | Aktiviert selektive Cache-Pfade. | Prod: Liste definieren (z. B. `/search|60|120`); dev: leer lassen. |
| `WATCHLIST_BACKOFF_BASE_MS`, `WATCHLIST_JITTER_PCT`, `WATCHLIST_RETRY_BUDGET_PER_ARTIST` | 250 ms / 0.2 / 6【F:app/config.py†L860-L890】 | Retry-/Backoff-Steuerung pro Künstler. | Prod: Budget + Backoff abhängig von Provider-Limits; dev: gering halten. |
| `FEATURE_MATCHING_EDITION_AWARE` | `True`【F:app/config.py†L345-L392】 | Matching-Engine berücksichtigt Edition-Tags. | Prod: belassen; dev: kann deaktiviert werden, um Performance zu vergleichen. |

## Minimal-Set für funktionierenden Start
1. `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` (App-Auth)【F:app/config.py†L493-L508】  
2. `SLSKD_BASE_URL` oder `SLSKD_URL` + `SLSKD_API_KEY` für Soulseek.【F:app/config.py†L565-L625】  
3. `DATABASE_URL` muss auf den Postgres-Dienst zeigen; der frühere eingebettete Default dient nur noch als Notfall-Smoke-Test.【F:app/config.py†L395-L410】
4. (Prod) `FEATURE_REQUIRE_AUTH=true` + `HARMONY_API_KEYS` / `HARMONY_API_KEYS_FILE`.【F:app/config.py†L895-L918】

## Profilempfehlung
- **Development:** `FEATURE_REQUIRE_AUTH=false`, `HARMONY_DISABLE_WORKERS=true`, `WATCHLIST_INTERVAL=300`, `CACHE_ENABLED=false`.  
- **Staging/Prod:** `FEATURE_REQUIRE_AUTH=true`, `FEATURE_RATE_LIMITING=true`, `INTEGRATIONS_ENABLED=spotify,slskd`, `CACHE_DEFAULT_TTL_S=60`, `HARMONY_DISABLE_WORKERS` unset.

