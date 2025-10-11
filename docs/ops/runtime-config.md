# Runtime Configuration Guide

Diese Anleitung ergänzt die Tabellen im [README](../../README.md#betrieb--konfiguration) und beschreibt, wie Harmony seine Laufzeitkonfiguration auflöst, welche Werte sicherheitskritisch sind und wie Feature-Flags zusammenspielen.

## Quellen & Priorität

1. **Code-Defaults** – sind in `app/config.py` hinterlegt (z. B. `DEFAULT_WATCHLIST_MAX_CONCURRENCY`).
2. **Datenbank-Settings** – bestimmte Schlüssel (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`, `SLSKD_URL`, `SLSKD_API_KEY`, `ENABLE_ARTWORK`, `ENABLE_LYRICS`) werden beim Start aus der Tabelle `settings` geladen und haben Vorrang vor ENV-Werten.
3. **Umgebungsvariablen** – werden zuletzt ausgewertet und überschreiben Defaults, sofern kein Datenbankwert existiert. Während der Laufzeit cached `get_app_config()` die Werte; Änderungen an `.env` erfordern daher einen Neustart.
4. **Runtime-Profile & Worker-Overrides** – `get_app_config().environment` bündelt `APP_ENV`, `HARMONY_DISABLE_WORKERS`, `WORKER_VISIBILITY_TIMEOUT_S`, `WATCHLIST_INTERVAL` sowie `WATCHLIST_TIMER_ENABLED`. Statt direkter `os.getenv()`-Zugriffe greifen Bootstrap, Queue-Persistence und Tests nun auf diese Single Source zurück.

> Tipp: Nutze `/settings` (GET/PUT), um Spotify- und slskd-Credentials zentral zu verwalten. Die API schreibt in die Datenbank und greift sofort für neue Requests.

## Sicherheitsempfehlungen

- API-Keys (`HARMONY_API_KEYS`, `HARMONY_API_KEYS_FILE`) und externe Secrets (`SPOTIFY_CLIENT_SECRET`, `SLSKD_API_KEY`, `MUSIXMATCH_API_KEY`) gehören in `.env` oder einen Secrets-Manager – niemals in Git.
- `AUTH_ALLOWLIST` sollte nur explizit benötigte Zusatzpfade enthalten. Health/Ready/Docs/OpenAPI werden automatisch freigeschaltet.
- Aktiviere `ERRORS_DEBUG_DETAILS` ausschließlich in geschützten Entwicklungsumgebungen – die Erweiterung schreibt Debug-Hints in den Response-Body.

## Feature-Gruppen & Flags

### Observability & Fehlerdiagnose

- Health-Checks honorieren `HEALTH_DB_TIMEOUT_MS`, `HEALTH_DEP_TIMEOUT_MS`, `HEALTH_DEPS` und `HEALTH_READY_REQUIRE_DB`. Nutze `docs/observability.md` für Detailbeispiele.

### Auth & CORS

- `FEATURE_REQUIRE_AUTH=true` bindet die API-Key-Dependency global ein. Setze den Flag nur für lokale Testläufe auf `false`.
- Die Allowlist wird aus Defaults (`/health`, `/ready`, `/health/ready`, `/docs`, `/redoc`, `/openapi.json`) plus `AUTH_ALLOWLIST` aufgebaut. `/api/health/ready` wird unabhängig vom API-Basispfad freigestellt.
- `ALLOWED_ORIGINS` akzeptiert CSV oder Zeilen. Ein leerer Wert blockt sämtliche Browser-Anfragen.

### Caching

- `CACHE_ENABLED` steuert die `ConditionalCacheMiddleware`. Feingranulare Regeln (`CACHEABLE_PATHS=/api/v1/library/*|300|600`) überschreiben das Default-TTL.
- Bei Cache-Fehlern sorgt `CACHE_FAIL_OPEN=true` dafür, dass die API weiterhin Live-Antworten liefert.

### Integrationen & Workers

- Spotify/slskd-Zeitlimits (`SPOTIFY_TIMEOUT_MS`, `SLSKD_TIMEOUT_MS`) greifen sowohl in REST-Endpunkten als auch in Workern (z. B. Watchlist).
- `WATCHLIST_*`-Variablen begrenzen Lastspitzen: reduziere `WATCHLIST_MAX_CONCURRENCY`, wenn sich Datenbank-Threads stauen, und beobachte I/O-Latenzen sowie Lock-Wartezeiten, bevor du die Parallelität erhöhst.
- Download-Retries (`RETRY_*`) konfigurieren die Sync-/Retry-Handler des Orchestrators; die historischen `RETRY_SCAN_*`-Werte werden nur noch für Legacy-Fallbacks gelesen.
- Der zentrale `RetryPolicyProvider` liest `RETRY_*` zur Laufzeit (inkl. Job-spezifischer Overrides wie `RETRY_SYNC_MAX_ATTEMPTS`) und cached das Ergebnis für `RETRY_POLICY_RELOAD_S` Sekunden. Nach Ablauf der TTL greifen neue ENV-Werte automatisch ohne Neustart; `SyncWorker.refresh_retry_policy()` erzwingt bei Bedarf eine sofortige Aktualisierung.
- Matching-Flags (`FEATURE_MATCHING_EDITION_AWARE`, `MATCH_*`) beeinflussen sowohl REST (`/matching`) als auch den Hintergrund-Worker.

### SQLite-Betrieb

- Standardmäßig nutzt Harmony SQLite (`sqlite+aiosqlite:///`). Produktionsprofile schreiben nach `/data/harmony.db`; Entwicklungsprofile nach `./harmony.db`. Tests verwenden eine In-Memory-Instanz.
- Setze `DB_RESET=1`, um den Datenbankfile beim Start zu löschen und das Schema frisch zu bootstrappen. Ohne das Flag bleibt der bestehende Inhalt erhalten.
- Prüfe, dass das über `DATABASE_URL` adressierte Verzeichnis existiert und beschreibbar ist (Health-Check `/api/health/ready`). Bei Container-Deployments sollte ein Volume `/data` gemountet werden.
- SQLite serialisiert Schreibzugriffe. Hohe Parallelität in Worker-Jobs lässt sich durch kleinere Batches (`WATCHLIST_*`, `RETRY_*`) und Warteschlangensteuerung kompensieren.
- Backups bestehen aus einem Kopieren der `.db`-Datei. Stoppe die Applikation oder setze `DB_RESET=0`, bevor du Snapshots ziehst, um Konsistenz zu gewährleisten.

## Frontend & Runtime Injection

- `VITE_API_BASE_URL` und `VITE_API_BASE_PATH` definieren die Basis-URL des Frontend-Clients.
- `VITE_REQUIRE_AUTH`/`VITE_AUTH_HEADER_MODE` spiegeln die Backend-Einstellungen (`FEATURE_REQUIRE_AUTH`, bevorzugter Header) und verhindern fehlkonfigurierte Browser-Clients.
- `VITE_RUNTIME_API_KEY` erlaubt das Injizieren eines Schlüssels via `<script>` – praktisch für statische Deployments hinter einem Secret-Store.
- `VITE_LIBRARY_POLL_INTERVAL_MS` steuert Poll-Intervalle der Library-Ansicht; das Backend selbst bleibt durch Watchlist-Intervalle geschützt.

## Änderungs-Workflow

1. Passe `.env` (oder Secret-Store) an und starte den Service neu.
2. Prüfe über `/api/v1/ready`, ob die Anwendung neue Einstellungen geladen hat.
3. Bei Spotify/slskd-Änderungen zusätzlich `/settings` aktualisieren, damit DB-Backups konsistent bleiben.
4. Halte Änderungen im CHANGELOG fest, insbesondere bei Flags mit Sicherheitsauswirkungen.

Weiterführende Beispiele und Best Practices findest du im Abschnitt „Betrieb & Konfiguration“ des README.
