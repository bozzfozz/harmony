# Vereinfachungsplan & Priorisierung (CODX-ANLY-097)

## Prioritätsmatrix
- **P0 – Quick Wins (≤ 1 Sprint, geringes Risiko)**
- **P1 – High Impact (1–2 Sprints, moderates Risiko)**
- **P2 – Nice-to-have (> 2 Sprints oder abhängig von Vorarbeiten)**

## Maßnahmen nach Priorität

### P0 – Quick Wins
1. **Router-Registry absichern & dokumentieren**  
   - **Beobachtung:** `router_registry.register_all` hängt die registrierten Router bereits zentral an die FastAPI-App, und die Konfigurationen (`register_domain`/`register_router`) leben gesammelt in `app/api/router_registry.py`; `app/main.py` nutzt ausschließlich diesen Pfad inklusive `compose_prefix` für die Standard-URLs.【F:app/api/router_registry.py†L73-L213】【F:app/main.py†L527-L570】  
   - **Schritte:**  
     1. Developer-Doku ergänzen (z. B. unter `docs/architecture`), die erklärt, wie neue Router über `register_domain` bzw. `register_router` eingehängt werden und warum direkte `include_router`-Aufrufe in `main` tabu sind.【F:app/api/router_registry.py†L73-L123】  
     2. Einen gezielten Test schreiben, der `router_registry.register_all` gegen ein frisches `FastAPI`-Objekt ausführt und sicherstellt, dass die erwarteten Domain-Prefixe montiert werden (Regression-Guard für zukünftige Router).【F:app/api/router_registry.py†L138-L176】  
     3. Im Registry-Modul eine kurze Kommentar-Sektion/Checkliste ergänzen, die beim Hinzufügen neuer Router an Tag-Etiketten und Prefix-Standards erinnert (Low-cost Governance im Code selbst).【F:app/api/router_registry.py†L179-L213】  
   - **Impact:** Weniger Boilerplate, sauberer Ausgangspunkt für Domänen-Module.  
   - **Aufwand:** 0.5–1 PT.  
   - **Risiko:** Niedrig (nur Verkabelung).  
   - **Rollback:** Revert der neuen Registry und Wiederherstellung der bisherigen `include_router`-Aufrufe.

2. **Logging-Hilfsfunktion vereinheitlichen (`log_event`)**
   - **Beobachtung:** `app/logging_events.log_event` dient bereits als zentraler Helper; der Search-Endpunkt nutzt ihn über `_emit_api_event`, hält aber noch einen Kompatibilitätspfad zu `app.routers.search_router.log_event` offen, während der `IntegrationService` seine Provider-Gateway-Aufrufe direkt mit `log_event` instrumentiert.【F:app/api/search.py†L103-L180】【F:app/services/integration_service.py†L109-L195】

   - **Schritte:**
     1. Kompatibilitäts-Shim `_emit_api_event` in `app/api/search.py` abbauen und Tests/Caller direkt auf `app.logging_events.log_event` ausrichten.
     2. Komponenten (Search, Worker, Services) auf konsistente Event-Felder prüfen und fehlende Helper-Nutzung nachziehen.
     3. Monitoring-Dokumentation mit vereinheitlichten Beispielen und Pflichtfeldern zur Structured-Logging-Konvention aktualisieren.
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
   - **Beobachtung:** `IntegrationService` initialisiert den `ProviderGateway` mit allen aktivierten Track-Providern und protokolliert Mehrquellen-Suchen via `log_event`, dennoch mappt `app/api/search.py` die API-Sources weiterhin manuell zu Providern und aggregiert Fehlerzustände selbst.【F:app/services/integration_service.py†L33-L195】【F:app/api/search.py†L125-L188】
   - **Schritte:**
     1. Source/Provider-Mapping sowie Statusaggregation aus `app/api/search.py` in Gateway bzw. `IntegrationService` überführen und als wiederverwendbare Antwortstruktur bereitstellen.
     2. Fehler- und Timeout-Kontrakte im Gateway harmonisieren, sodass Router und Services die gleichen Result-/Statusfelder konsumieren.
     3. Search- und Integrations-Router auf das neue Mehrquellen-Response-Modell umstellen und Tests/Schema-Dokumentation entsprechend aktualisieren.
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

## 2025-10-06 – Radix UI bump & Test-Polyfills
- Frontend-Abhängigkeiten (`@radix-ui/react-*`, Testing-Library, Tailwind/Vite Toolchain) auf aktuelle Minor-/Patch-Stände gebracht, damit der Dev-Server wieder ohne Peer-Warnungen startet.
- Jest-Setup ergänzt einen dedizierten Pointer-Capture-Polyfill für `hasPointerCapture`/`releasePointerCapture`, damit jsdom ≥20 keine Laufzeitfehler wirft.
- Neue Radix-Smoke-Tests (Select, Tabs, Switch, Toast) sichern die Basisinteraktionen für Keyboard- und Pointer-Nutzung ab und verhindern Regressionen nach weiteren Bumps.【F:frontend/src/__tests__/radix.smoke.test.tsx†L1-L129】【F:frontend/jest.config.cjs†L6-L14】【F:frontend/src/tests/setup/polyfills.pointerCapture.ts†L1-L10】

