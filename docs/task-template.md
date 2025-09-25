# TASK_ID: <EINDEUTIGE-ID>
# Titel: <KURZER, HANDLUNGSORIENTERTER TITEL>

## Ziel
Beschreibe in 1–3 Sätzen **was** gebaut wird und **warum**. Formuliere das Endverhalten aus Nutzer- oder System-Perspektive.

## Kontext
- Repository: <org/repo> (Branch: <branch>)
- Verbindliche Standards: **AGENTS.md**, ggf. **docs/ui-design-guidelines.md** (für Frontend)
- Bestehende Module, die betroffen sind: <pfade/zu/modulen>
- Abhängigkeiten (APIs, Dienste): <Spotify/Plex/slskd/etc.>

> **Pflicht** (Preflight):  
> - Lies **AGENTS.md** vollständig und befolge Commit-/Review-/Sicherheits-/Style-Regeln.  
> - Wenn Frontend: Lies **docs/ui-design-guidelines.md** (Farben, Typo, Spacing, Komponenten, Interaktionen).  
> - **Keine** `BACKUP`-Dateien erstellen/ändern.  
> - **Keine** Lizenzdatei verändern.  
> - **Keine** Geheimnisse in Code/Repo commiten.

---

## Scope
- **In Scope**: Konkrete Funktionen, Pfade, Datenflüsse, die in diesem Task umgesetzt werden müssen.
- **Out of Scope**: Bewusst nicht enthaltene Dinge (z. B. UI, wenn Backend; oder externe Integrationen).

## Architektur & Datenfluss
- **Komponenten**: <Service/Worker/Router/Frontend-Page/Hook>
- **Sequenz** (vereinfacht):  
  1) <Ereignis A> → 2) <Worker/Handler> → 3) <Persistenz/Antwort>  
- **Nebenläufigkeit**: <Queues/Locks/Rate-Limits/Parallelität>  
- **Idempotenz**: <Wie erneutes Ausführen ohne Doppelwirkung sichergestellt wird>  
- **Fehlerpfade**: <Was passiert bei Timeout/API-Fehler/Validierungsfehler>

## API-Vertrag (falls zutreffend)
**Neue/angepasste Endpunkte** (exakte Spezifikation):
- `METHOD /pfad` — **Beschreibung**  
  - **Query/Body**: (Typen & Validierungen)  
  - **Statuscodes**: 200, 202, 400, 404, 429, 500  
  - **Antwort (Beispiel)**:
    ```json
    {
      "ok": true,
      "data": {...},
      "error": null
    }
    ```
  - **Fehler (Beispiel)**:
    ```json
    {
      "ok": false,
      "error": {"code":"VALIDATION_ERROR","message":"<hinweis>"}
    }
    ```
- **Fehler-Codes (Kanonisch)**: `VALIDATION_ERROR`, `NOT_FOUND`, `RATE_LIMITED`, `DEPENDENCY_ERROR`, `INTERNAL_ERROR`

## Datenbank (falls zutreffend)
- **Schema-Änderungen**:
  - Tabelle `<name>`: Spalten `foo VARCHAR(255) NULL`, `bar INTEGER DEFAULT 0`
- **ORM-Modelle**: Exakte Felder/Typen/Defaults
- **Migration**:
  - SQLite-safe, idempotent: Spalten nur hinzufügen, wenn nicht existent
  - Kein Datenverlust; Rollback-Strategie beschreiben

## Konfiguration
- **ENV-Variablen**: `FEATURE_X_ENABLED` (default: `false`), `TIMEOUT_MS` (default: 15000)
- **Defaults**: Sicher & konservativ, dokumentieren
- **Feature-Flag**: Umschalten ohne Redeploy ermöglichen

## Sicherheit
- **Secrets** nur via ENV/Secret-Store; nie im Code.  
- **Validierung/Deserialisierung**: strikte Schemas, Grenzwerte, Whitelists.  
- **Command Execution/FS**: Pfade normalisieren, keine unsicheren Shell-Aufrufe.  
- **SSRF/CORS/CSRF**: falls relevant, Regeln definieren.

## Performance & Zuverlässigkeit
- **Timeouts**: HTTP <X>s, IO <Y>s  
- **Retries**: Max <N>, Backoff: expon./Jitter  
- **Rate-Limits**: pro Dienst <Wert>  
- **Speicher/CPU**: keine ungebremsten Sammlungen/Loops

## Logging & Observability
- **Log-Level**: INFO default; DEBUG hinter Flag  
- **Struktur**: `event`, `entity_id`, `duration_ms`, `status`  
- **Metriken**: <Zähler/Latenz/Fehlerrate> (optional)

## Änderungen an Dateien
> Liste **präzise**, was **neu**, **geändert**, **gelöscht** wird (mit Pfad):

- **Neu**
  - `app/utils/<neue_datei>.py` — <kurzbeschreibung>
  - `app/workers/<neuer_worker>.py` — <kurzbeschreibung>
  - `frontend/pages/<neue_page>.tsx` — <kurzbeschreibung>
- **Geändert**
  - `app/workers/sync_worker.py` — Hook einfügen: <was/genau>
  - `app/routers/<router>.py` — Endpunkt ergänzen: <welcher>
  - `app/models.py` — Modell `<Name>` um Felder `<f1,f2>` erweitern (Defaults!)
- **Gelöscht**
  - *(nur wenn nötig; sonst leer lassen)*

## Implementierungsschritte (Checkliste)
1. Preflight: Standards lesen (**AGENTS.md**, ggf. **docs/ui-design-guidelines.md**).
2. Models/DB: Schema-Erweiterung + idempotente Init/Alter-Logik.
3. Core-Logik: Implementiere <Service/Worker/Handler> gemäß Datenfluss.
4. API/Router: Endpunkte inkl. Validierung & Fehlercodes.
5. Konfiguration: ENV-Variablen + Defaults.
6. Logging/Metriken: sinnvolle Events platzieren.
7. Tests: Unit/Integration (siehe unten).
8. Doku: README/CHANGELOG/Docs aktualisieren.
9. CI: Lint/Format/Test prüfen & grün.

## Tests
- **Unit-Tests** (Beispiele):
  - `tests/test_<topic>.py::test_success_path()`
  - `tests/test_<topic>.py::test_validation_error()`
  - `tests/test_<topic>.py::test_dependency_timeout_retry()`
- **Integration-Tests**:
  - End-to-End-Fluss: <Eingabe> → <Worker/Router> → <DB/API Ergebnis>
- **Coverage-Ziel**: ≥ 85% in geänderten Modulen
- **Stubs/Mocks**: Externe Dienste mocken (Spotify/Plex/slskd etc.)

## Definition of Done (DoD)
- [ ] Alle neuen/angepassten Tests grün: `pytest -q`
- [ ] Linting/Formatting: `ruff check .` & `black --check .` ohne Fehler
- [ ] **Keine** `BACKUP`-Datei erstellt/verändert
- [ ] API-Vertrag eingehalten (Statuscodes, Payloads, Fehlercodes)
- [ ] Idempotent & nebenläufig sicher
- [ ] Doku aktualisiert: `README.md`, `CHANGELOG.md`, ggf. `docs/*.md`
- [ ] Keine Secrets/Schlüssel im Code/Repo

## Manuelle QA (Schritte)
1. Starte Service/Dev-Stack (`docker compose up`) mit minimalen ENV-Defaults.
2. Trigger <Endpoint/Aktion> mit Beispielpayload A → erwarte Ergebnis B.
3. Fehlerfall simulieren (Timeout/Bad Input) → erwarte Fehlercode & Log.
4. Wiederholung (Idempotenz) → keine Duplikate, konsistenter Zustand.

## CI/CD
- Pipeline muss **alle** Schritte ausführen:
  - `pip install -r requirements.txt`
  - `ruff check .`
  - `black --check .`
  - `pytest -q`
- Kein neuer Job darf bestehende Pipelines brechen.

## PR & Commits
- **Commit-Format** (Conventional Commits):  
  - `feat: …` / `fix: …` / `docs: …` / `test: …` / `chore: …`
- **PR-Beschreibung** MUSS enthalten:
  - Kurzfassung, **Was/Warum**
  - Änderungen an Dateien
  - Migrationshinweise
  - Testnachweise (Screens/Logs)
  - Risiken/Limitierungen
  - Verweis auf **AGENTS.md**-Konformität

## Offene Fragen (falls vorhanden)
- <Liste spezifischer Unklarheiten, die vor Umsetzung geklärt werden sollen>

---

## Beispiel (ausgefüllt, kurz)
- **In Scope**: `POST /feature/do-thing` + Worker-Hook + DB-Feld `thing_status`
- **Out of Scope**: Frontend-UI
- **API**: `POST /feature/do-thing` → 202, `GET /feature/status/{id}` → 200/404
- **DB**: Spalte `thing_status TEXT DEFAULT 'pending'`
- **ENV**: `THING_TIMEOUT_MS=15000`
- **Retry**: max 3, Backoff 0.5×2^n, Jitter ±20%
- **Tests**: success, validation error, dependency timeout→retry→success
- **DoD**: alle Checks grün, Doku aktualisiert, idempotent, keine BACKUP
