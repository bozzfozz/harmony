# Vereinfachungsplan & Priorisierung (CODX-ANLY-097)

## Prioritätsmatrix
- **P0 – Quick Wins (≤ 1 Sprint, geringes Risiko)**
- **P1 – High Impact (1–2 Sprints, moderates Risiko)**
- **P2 – Nice-to-have (> 2 Sprints oder abhängig von Vorarbeiten)**

## Maßnahmen nach Priorität

### P0 – Quick Wins
1. **Router-Gruppierung & gemeinsame Prefix-Factory aufsetzen**  
   - **Beobachtung:** `app/main.py` registriert 17 Router manuell; Prefix-Logik (z. B. `/spotify`, `/spotify/backfill`) wird dupliziert.【F:app/main.py†L178-L201】  
   - **Schritte:**  
     1. Neues Modul `app/api/router_registry.py` anlegen, das Router nach Domänen (Spotify, Soulseek, System) bündelt.  
     2. Einheitliche Prefix-Factory einführen (`compose_prefix(base_path, suffix)`), die sowohl in `main` als auch Tests genutzt wird.  
     3. `app/main.py` auf Registry umstellen, damit spätere Konsolidierung nur an einer Stelle erfolgt.  
   - **Impact:** Weniger Boilerplate, sauberer Ausgangspunkt für Domänen-Module.  
   - **Aufwand:** 0.5–1 PT.  
   - **Risiko:** Niedrig (nur Verkabelung).  
   - **Rollback:** Revert der neuen Registry und Wiederherstellung der bisherigen `include_router`-Aufrufe.

2. **Logging-Hilfsfunktion einführen (`log_event`)**  
   - **Beobachtung:** Cache nutzt `extra={"event": …}`, Watchlist-Worker und Search-Router codieren Schlüssel im Nachrichtentext.【F:app/services/cache.py†L70-L135】【F:app/workers/watchlist_worker.py†L93-L103】【F:app/routers/search_router.py†L127-L154】  
   - **Schritte:**
     1. Utility `app.logging_events.log_event(logger, event, **fields)` bereitstellen.
     2. In kritischen Komponenten (Search, Watchlist, Orchestrator) auf das neue Helper wechseln.
     3. Monitoring-Doku ergänzen (Event- und Pflichtfelder siehe Logging-Contract).  
   - **Impact:** Vereinheitlichte Logs → schnellere Observability-Gewinne.  
   - **Aufwand:** 1 PT.  
   - **Risiko:** Niedrig (Log-Only).  
   - **Rollback:** Helper entfernen; alte Logzeilen wiederherstellen.

3. **Worker-Konfigurations-Defaults im Code dokumentieren & konsolidieren**  
   - **Beobachtung:** Watchlist-/Retry-Worker lesen ENV (`WATCHLIST_*`, `RETRY_*`) ohne zentrale Übersicht; Config-Matrix liefert bereits Dokumentation.【F:app/workers/watchlist_worker.py†L61-L118】【F:app/workers/persistence.py†L42-L103】【F:app/main.py†L239-L323】  
   - **Schritte:**  
     1. `docs/workers.md` (neu) mit Defaultwerten + Overrides aus Config-Matrix erstellen.  
     2. `app/main.py` beim Start `logger.info("worker_config", …)` über gemeinsame Helper ausgeben.  
     3. Hinweis in README (Roadmap) verlinken.  
   - **Impact:** Schnellere Diagnose bei Fehlkonfiguration, Grundlage für spätere Profile.  
   - **Aufwand:** 0.5 PT.  
   - **Risiko:** Sehr gering.  
   - **Rollback:** Doc löschen.

### P1 – High Impact
1. **Worker-Orchestrator als eigenständigen Service implementieren** *(erledigt – siehe `app/orchestrator/*` seit CODX-ORCH-084)*
   - **Beobachtung:** `_start_background_workers` erstellt Worker-Instanten direkt und speichert sie im App-State; Stop-Logik iteriert hartkodierte Attribute.【F:app/main.py†L239-L352】【F:app/main.py†L337-L352】  
   - **Schritte:**  
     1. Klasse `WorkerOrchestrator` erstellen (Konfiguration, Start/Stop, Health-Report).  
     2. `app.main.lifespan` refaktorisieren: Orchestrator aus App-State lesen, Worker definieren via Registry (Mapping Name → Factory).  
     3. CLI/Router-Hooks (z. B. `/system/reload`) auf Orchestrator aufsetzen.  
   - **Impact:** Bessere Testbarkeit, klarer Shutdown, Vorbereitung für DLQ/Retries.  
   - **Aufwand:** 1–2 Sprints.  
   - **Risiko:** Mittel (Lifecycle/Async).  
   - **Rollback:** Orchestrator entfernen und alten Lifecycle wiederherstellen.

2. **ProviderGateway + Adapter-Contracts vereinheitlichen**  
   - **Beobachtung:** `IntegrationService` behandelt nur `SlskdAdapter`; Spotify/Plex-Adapter werden zwar erstellt, aber nicht genutzt.【F:app/services/integration_service.py†L31-L86】【F:app/integrations/registry.py†L16-L58】  
   - **Schritte:**  
     1. `IntegrationService.search_tracks` auf generische `MusicProviderAdapter` umstellen.  
     2. Timeout/Retry-Policy zentralisieren (ein Decorator oder Wrapper im Gateway).  
     3. Router (`search`, `integrations`) auf den Gateway refaktorisieren; Response-Modelle angleichen.  
   - **Impact:** Mehr Provider in Zukunft möglich, weniger Sonderfälle, klare Fehlercodes.  
   - **Aufwand:** 1 Sprint.  
   - **Risiko:** Mittel (Async, Error-Mapping).  
   - **Rollback:** Gateway deaktivieren, alte Methode reaktivieren.

3. **Spotify-Domäne konsolidieren (Router & Services)**
   - **Beobachtung:** `app/api/spotify.py` bündelt `core_router`, `backfill_router`, `free_router` und `free_ingest_router`; Legacy-Wrapper unter `app/routers/*.py` warnen nur noch vor der Alt-Nutzung.【F:app/api/spotify.py†L60-L1233】【F:app/api/routers/spotify.py†L1-L13】
   - **Schritte:**
     1. Domänen-Service `SpotifyDomainService` etabliert halten (auth-Status, Playlist-IO, Free-Import).
     2. Aufrufer konsequent auf das neue Modul umstellen und verbleibende Legacy-Wrapper abbauen.
     3. Überflüssige Duplicate-Validierungen entfernen, Response-Models teilen.
   - **Impact:** Geringere Duplikate, klarer Verantwortungsbereich Spotify.
   - **Aufwand:** 1–2 Sprints.
   - **Risiko:** Mittel (viele Endpoints).
   - **Rollback:** Legacy-Wrapper beibehalten und alten Stand wiederverwenden.

### P2 – Nice-to-have
1. **Generierter API-Client für das Frontend**
   - **Beobachtung:** `frontend/src/api/client.ts` und die Service-Module (`frontend/src/api/services/*.ts`) enthalten ~470 Zeilen manuell gepflegter Fetch-Logik inklusive wiederholter Routenstrings.【F:frontend/src/api/client.ts†L18-L409】【F:frontend/src/api/services/downloads.ts†L180-L241】
   - **Schritte:** OpenAPI-Schema exportieren (`app.main` → `get_openapi`), Client via `openapi-typescript-codegen` generieren, lokale Hooks migrieren.  
   - **Impact:** Weniger Drift, Typsicherheit.  
   - **Aufwand:** 2+ Sprints (inkl. Anpassung der Tests).  
   - **Risiko:** Mittel (Breaking Changes an Aufrufercode).

2. **Konfigurationsprofile (dev/test/prod) einführen**  
   - **Beobachtung:** ENV-Defaults liegen über `os.getenv` verteilt; dev/test benötigen unterschiedliche Worker/Rate-Limits.【F:app/config.py†L200-L299】【F:app/main.py†L239-L323】  
   - **Schritte:**  
     1. `config/profiles/{dev,prod}.env` definieren.  
     2. `load_config` um Profil-Auswahl (`HARMONY_PROFILE`) erweitern.  
     3. Dokumentation & CI-Anpassung.  
   - **Impact:** Einfachere lokale Inbetriebnahme, weniger Fehlkonfiguration.  
   - **Aufwand:** 2 Sprints.  
   - **Risiko:** Niedrig-mittel (ENV-Umstellung).

3. **Async DB-IO für Watchlist-DAO evaluieren**  
   - **Beobachtung:** Watchlist-Worker nutzt `dao` mit Thread-/Async-Modus Umschaltung; `thread` ist Default.【F:app/workers/watchlist_worker.py†L71-L118】  
   - **Schritte:**  
     1. SQLAlchemy Async-Engine prüfen, DAO anpassen.  
     2. Performance-Tests für Batch-Ladevorgänge.  
     3. Rollout mit Feature-Flag.  
   - **Impact:** Potenziell geringere Latenz beim Polling.  
   - **Aufwand:** 2–3 Sprints.  
   - **Risiko:** Mittel (DB/Async).

## Abhängigkeiten & Sequenzierung
- **Voraussetzungen für P1**: Logging-Hilfsfunktion und Router-Registry (P0) sollten zuerst umgesetzt werden, um Konflikte zu minimieren.  
- **Worker-Orchestrator** (P1.1) bildet Grundlage für Spotify-Domänenkonsolidierung und spätere Retry-Strategien.  
- **ProviderGateway** kann parallel zu Logging-Standardisierung erfolgen, benötigt aber Tests für Timeout- und Fehlerkodes.

## Risiken & Rollback-Strategie
- Für jede Maßnahme existiert eine natürliche Revert-Strategie (klassischer Git-Revert).  
- Kritische Umbauten (Orchestrator, ProviderGateway) sollten hinter Feature-Flags (`FEATURE_WORKER_ORCHESTRATOR`, `FEATURE_PROVIDER_GATEWAY`) ausgerollt werden, um gezielt umzuschalten.【F:app.config.py†L200-L299】

