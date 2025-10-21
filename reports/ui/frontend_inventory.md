# Frontend Inventory – CODX-FE-HTMX-PLAN-001

## Überblick
Die aktuelle Harmony-Codebasis stellt umfangreiche Verwaltungs-Endpunkte bereit, die künftig durch das `/ui` Frontend konsumiert werden sollen. Alle fachlichen Domains sind unter `/api/v1` registriert, ergänzt durch spezifische Health-Routen unter `/api/health` und OAuth-Hilfsendpunkte.【F:app/api/router_registry.py†L37-L223】【F:app/api/health.py†L10-L27】【F:app/api/oauth_public.py†L22-L104】 Die folgende Inventur ordnet die Endpunkte den geplanten UI-Ansichten zu und markiert potenzielle Risiken.

## Backend-Endpunkte nach Domäne
### Suche & Matching
- `POST /api/v1/search` aggregiert Ergebnisse aus Spotify & Soulseek inklusive Scoring und Fehlerpropagation.【F:app/api/search.py†L158-L209】
- `POST /api/v1/matching/spotify-to-soulseek` persistiert Match-Ergebnisse und reichert Downloads um Metadaten an.【F:app/routers/matching_router.py†L90-L153】

### Downloads & Soulseek
- Download-Workflow (`GET/POST/PATCH/DELETE /api/v1/download/...`) verwaltet Listen, Prioritäten, Retry und Exporte.【F:app/routers/download_router.py†L45-L240】
- Soulseek-spezifische Operationen liefern Suchergebnisse, queue Downloads, verwalten Artefakte (Lyrics, Artwork) und erlauben Requeue/Cancel über `/api/v1/soulseek/...`.【F:app/routers/soulseek_router.py†L75-L719】

### Jobs, DLQ & Orchestrator
- Dead-Letter-Queue Endpunkte (`/api/v1/dlq`) listen, requeue'n, purgen und liefern Statistiken.【F:app/routers/dlq_router.py†L170-L250】
- Metadata-Worker Steuerung unter `/api/v1/metadata/update|status|stop` mit Worker-Verfügbarkeitsprüfung.【F:app/routers/metadata_router.py†L19-L86】
- Manuelle Sync-Auslösung via `POST /api/v1/sync` inkl. Fehlermeldung bei fehlenden Credentials.【F:app/routers/sync_router.py†L26-L106】

### Spotify & Integrationen
- Spotify-Domain deckt Status, Suchen, Playlists, Backfill und FREE-Ingest ab (`/api/v1/spotify/...`, `/api/v1/spotify/free/...`, `/api/v1/spotify/import/...`).【F:app/api/spotify.py†L65-L210】
- OAuth-Public-Endpunkte (`/api/v1/oauth/start|manual|status|health`) orchestrieren Auth-Flows und Ratelimits.【F:app/api/oauth_public.py†L22-L104】
- Integration-Gesundheit: `GET /api/v1/integrations` liefert Provider-Statusberichte.【F:app/routers/integrations.py†L34-L47】

### Watchlist & Artists
- `/api/v1/watchlist` stellt CRUD, Pause/Resume und Prioritätsupdates bereit.【F:app/api/watchlist.py†L56-L227】
- Künstler-spezifische Routen (`/api/v1/artists/...`) unterstützen Watchlist-Ansicht, Enqueue und Detail-Abrufe.【F:app/api/artists.py†L66-L214】

### Aktivität & Monitoring
- Aktivitätsfeed (`GET /api/v1/activity`) und Exporte (`/api/v1/activity/export`).【F:app/routers/activity_router.py†L25-L157】
- Systemstatus & Health: `/api/v1/status`, `/api/v1/health`, `/api/v1/ready`, `/api/v1/metrics` und `/api/v1/secrets/{provider}/validate` bündeln Uptime, Abhängigkeits- und Secrets-Checks.【F:app/api/system.py†L106-L220】【F:app/api/system.py†L344-L368】
- Spezifische Service-Health-Badges: `/api/v1/health/spotify`, `/api/v1/health/soulseek`.【F:app/routers/health_router.py†L15-L33】
- Allgemeine Liveness/Readiness unter `/api/health/live|ready` für Infrastruktur-Monitoring.【F:app/api/health.py†L10-L27】

### Einstellungen & Imports
- Settings-Routen (`/api/v1/settings` + `/history`, `/artist-preferences`) kapseln Konfigurationswerte und Historien.【F:app/routers/settings_router.py†L39-L151】
- Spotify FREE Import: `POST /api/v1/imports/free` validiert Payloads, persisted Sessions & Batch-Datensätze.【F:app/routers/imports_router.py†L34-L140】

## Wiring-Matrix (API ↔ UI)
| Geplante UI-Komponente | Verknüpfte Endpunkte | Zweck |
|------------------------|----------------------|-------|
| Dashboard KPI-Karten | `/api/v1/status`, `/api/v1/health` | Laufzeitstatus & abhängige Dienste visualisieren.【F:app/api/system.py†L106-L191】【F:app/api/system.py†L344-L368】 |
| Spotify-Verbindungsmodul | `/api/v1/spotify/status`, `/api/v1/oauth/start`, `/api/v1/oauth/manual` | Auth-Status anzeigen & OAuth-Flows durchführen.【F:app/api/spotify.py†L113-L162】【F:app/api/oauth_public.py†L22-L62】 |
| Suchresultat-Liste | `POST /api/v1/search`, `POST /api/v1/download`, `POST /api/v1/soulseek/search` | Kandidaten anzeigen, Downloads triggern, Soulseek-Ansicht liefern.【F:app/api/search.py†L158-L209】【F:app/routers/download_router.py†L163-L190】【F:app/routers/soulseek_router.py†L75-L118】 |
| Download-Tabelle | `/api/v1/downloads`, `/api/v1/download/{id}/priority`, `/api/v1/download/{id}/retry` | Queue verwalten, Prioritäten ändern, Retries auslösen.【F:app/routers/download_router.py†L45-L240】 |
| Jobs-Dashboard | `/api/v1/dlq`, `/api/v1/metadata/...`, `/api/v1/sync`, `/api/v1/downloads` | DLQ, Metadata-Status, Sync und Download-Queue monitoren; Soulseek-Aktionen laufen über `/api/v1/soulseek/...`, die Queue-Daten stammen aus `/api/v1/downloads`.【F:app/routers/dlq_router.py†L170-L239】【F:app/routers/metadata_router.py†L19-L77】【F:app/routers/sync_router.py†L26-L106】【F:app/routers/download_router.py†L45-L240】【F:app/routers/soulseek_router.py†L623-L633】 |
| Watchlist-Grid | `/api/v1/watchlist`, `/api/v1/watchlist/{artist}` Varianten | Künstler priorisieren, pausieren, löschen.【F:app/api/watchlist.py†L56-L227】 |
| Aktivitätsfeed | `/api/v1/activity`, `/api/v1/activity/export` | Event-Stream anzeigen und exportieren.【F:app/routers/activity_router.py†L25-L157】 |
| Settings-Formulare | `/api/v1/settings`, `/api/v1/settings/history`, `/api/v1/settings/artist-preferences` | Konfiguration verwalten & Audits nachvollziehen.【F:app/routers/settings_router.py†L39-L151】 |
| Systemdiagnostik | `/api/health/live`, `/api/health/ready`, `/api/v1/integrations`, `/api/v1/secrets/{provider}/validate` | Betriebsdiagnosen & Secrets-Checks bereitstellen.【F:app/api/health.py†L10-L27】【F:app/routers/integrations.py†L34-L47】【F:app/api/system.py†L204-L220】 |
| Imports-Feedback | `POST /api/v1/imports/free` | Ergebnisse der Playlist-Link-Verarbeitung anzeigen.【F:app/routers/imports_router.py†L34-L140】 |

## Risiken & Blocker
1. **Worker-Verfügbarkeit** – Metadata-, Sync- und Soulseek-Routen liefern 503/409, wenn Worker fehlen oder Jobs blockiert sind; UI muss Fallback-Zustände anzeigen.【F:app/routers/metadata_router.py†L19-L86】【F:app/routers/sync_router.py†L26-L106】【F:app/routers/soulseek_router.py†L635-L719】
2. **OAuth-Flow-Abhängigkeiten** – Fehlkonfigurierte Redirect-URIs oder Ratelimits im manuellen Flow bremsen Spotify-Seite; Konfig-Abgleich nötig.【F:app/api/oauth_public.py†L22-L83】
3. **DLQ-Bedienbarkeit** – Ohne aktiven Sync-Worker schlägt `/api/v1/dlq/requeue` fehl; UI muss Aktionen deaktivieren oder klar warnen.【F:app/routers/dlq_router.py†L200-L220】
4. **Große Payloads** – FREE-Importe und Download-Listen können umfangreich werden; Pagination & Limits bereits vorhanden, UI muss sie respektieren.【F:app/routers/imports_router.py†L34-L140】【F:app/routers/download_router.py†L45-L73】
5. **Security-Header** – CSRF- und Session-Controls sind inzwischen verdrahtet: `_ensure_csrf_token` stellt pro Sitzung signierte Tokens bereit, während `attach_csrf_cookie` sie als `csrftoken`-Cookie persistiert und die View-Kontexte sie in `<meta name="csrf-token">` einbetten, sodass `ui-bootstrap.js` den `X-CSRF-Token` Header für HTMX-Requests setzt.【F:app/ui/routes/shared.py†L114-L119】【F:app/ui/csrf.py†L72-L87】【F:app/ui/context/dashboard.py†L51-L75】【F:app/ui/static/js/ui-bootstrap.js†L9-L22】 Verbleibendes Risiko: Neue UI-Flows, die eigene Fetch-/XHR-Pfade oder eingebettete Widgets nutzen, müssen weiterhin den Header propagieren, sonst greifen die `enforce_csrf`-Guards nicht.【F:app/ui/csrf.py†L118-L140】

