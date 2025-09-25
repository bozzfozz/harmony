# TASK_ID: <EINDEUTIGE-ID>
# Titel: <KURZER, HANDLUNGSORIENTERTER TITEL>

## Ziel
Beschreibe in 1–3 Sätzen **was** gebaut wird und **warum**. Formuliere das Endverhalten aus Nutzer- oder System-Perspektive.

---

## Kontext
- **Repository:** <org/repo> (Branch: <branch>)
- **Verbindliche Standards:** `AGENTS.md`, ggf. `docs/ui-design-guidelines.md` (für Frontend)
- **Betroffene Module:** <pfade/zu/modulen>
- **Abhängigkeiten (APIs/Dienste):** <Spotify/Plex/slskd/etc.>
- **Vorbedingungen (Preflight – verpflichtend):**
  - [ ] `AGENTS.md` vollständig gelesen (Commit-/Review-/Security-/Style-Regeln einhalten)
  - [ ] Falls Frontend: `docs/ui-design-guidelines.md` gelesen (Farben, Typo, Spacing, Komponenten, Interaktionen)
  - [ ] **Keine** `BACKUP`-Dateien erstellen/ändern; **keine** Lizenzdatei ändern
  - [ ] **Keine Secrets**/Zugangsdaten ins Repo committen

---

## Scope
- **In Scope:** Konkrete Funktionen, Pfade, Datenflüsse, die umgesetzt werden
- **Out of Scope:** Bewusst ausgeschlossen (z. B. UI weglassen, wenn nur Backend)

---

## 🔐 Kompatibilitätsvertrag (required)
- **Public API/Function/Endpoint:** z. B. `get_album_tracks_normalized(album_id) -> List[Track]` / `GET /api/feature`
- **Rückgabetyp & Iterationsgarantie:** z. B. *Iterable Liste von Track-Objekten, kein Dict*
- **Fehlerkontrakt:** Exceptions/HTTP-Codes (kanonisch: `VALIDATION_ERROR`, `NOT_FOUND`, `RATE_LIMITED`, `DEPENDENCY_ERROR`, `INTERNAL_ERROR`)
- **Stabilitätsklasse:** `stable` | `beta`
- **Breaking-Change-Regel:** Breaking Changes nur mit Major-Bump + Migrationshinweis (CHANGELOG + Docs)

---

## Architektur & Datenfluss
- **Komponenten:** <Service/Worker/Router/Frontend-Page/Hook>
- **Sequenz (vereinfacht):**
  1) <Ereignis A> → 2) <Worker/Handler> → 3) <Persistenz/Antwort>
- **Nebenläufigkeit:** Queues/Locks/Rate-Limits/Parallelität
- **Idempotenz:** Wie Wiederholung ohne Doppelwirkung sichergestellt wird
- **Fehlerpfade:** Timeout, Dependency-Fehler, Validierungsfehler (inkl. Retry/Backoff)

---

## API-Vertrag (falls zutreffend)
**Neue/angepasste Endpunkte (exakte Spezifikation):**
- `METHOD /pfad` — **Beschreibung**
  - **Query/Body**: Typen & Validierungen (Pydantic/TS-Typen)
  - **Statuscodes:** 200, 202, 400, 404, 429, 500
  - **Antwort (Beispiel)**:
    ```json
    { "ok": true, "data": { }, "error": null }
    ```
  - **Fehler (Beispiel)**:
    ```json
    { "ok": false, "error": { "code": "VALIDATION_ERROR", "message": "<hinweis>" } }
    ```

- **OpenAPI-Gate (required):** `/openapi.json` muss den Vertrag widerspiegeln (Array vs. Object, Feldnamen, Pflichterfordernisse)

---

## Datenbank (falls zutreffend)
- **Schema-Änderungen:**
  - Tabelle `<name>`: Spalten `foo VARCHAR(255) NULL`, `bar INTEGER DEFAULT 0`
- **ORM-Modelle:** Exakte Felder/Typen/Defaults
- **Migration/Init:**
  - SQLite-safe, **idempotent** (Spalten nur hinzufügen, wenn nicht existent)
  - Kein Datenverlust; **Rollback-Strategie** dokumentieren

---

## Konfiguration
- **ENV-Variablen:** `FEATURE_X_ENABLED` (default: `false`), `TIMEOUT_MS` (default: `15000`)
- **Defaults:** konservativ & sicher, dokumentieren
- **Feature-Flag:** Umschalten ohne Redeploy ermöglichen

---

## Sicherheit
- Secrets nur via ENV/Secret-Store
- Strikte Validierung/Deserialisierung (Grenzwerte/Whitelists)
- Dateisystem/Shell: Pfade normalisieren, keine unsicheren Shell-Aufrufe
- SSRF/CORS/CSRF-Regeln (falls relevant) definieren

---

## Performance & Zuverlässigkeit
- **Timeouts:** HTTP <X>s, IO <Y>s
- **Retries:** Max <N>, Backoff expon. + Jitter
- **Rate-Limits:** pro Dienst <Wert>
- **Ressourcen:** keine ungebremsten Sammlungen/Loops; Speicher/CPU beachten

---

## Logging & Observability
- **Level:** INFO default; DEBUG hinter Flag
- **Strukturierte Logs:** `event`, `entity_id`, `duration_ms`, `status`
- **Metriken (optional):** Zähler, Latenz, Fehlerrate

---

## Änderungen an Dateien
> Liste **präzise**, was **neu**, **geändert**, **gelöscht** wird (mit Pfad):

- **Neu**
  - `app/utils/<neue_datei>.py` — <Kurzbeschreibung>
  - `app/workers/<neuer_worker>.py` — <Kurzbeschreibung>
  - `frontend/pages/<neue_page>.tsx` — <Kurzbeschreibung>
- **Geändert**
  - `app/workers/sync_worker.py` — Hook einfügen: <genau was>
  - `app/routers/<router>.py` — Endpunkt ergänzen: <welcher>
  - `app/models.py` — Modell `<Name>` um Felder `<f1,f2>` erweitern (mit Defaults!)
- **Gelöscht**
  - *(nur wenn nötig; sonst leer lassen)*

---

## Implementierungsschritte (Checkliste)
1. Preflight: `AGENTS.md` (und ggf. `docs/ui-design-guidelines.md`) lesen
2. Models/DB: Schema-Erweiterung + idempotente Init/Alter-Logik
3. Core-Logik: <Service/Worker/Handler> gemäß Datenfluss
4. API/Router: Endpunkte inkl. Validierung & Fehlercodes
5. Konfiguration: ENV-Variablen + Defaults
6. Logging/Metriken: sinnvolle Events platzieren
7. Tests (Unit/Contract/E2E) erstellen/aktualisieren
8. Doku: README/CHANGELOG/Docs aktualisieren
9. CI: Lint/Format/Test prüfen & grün

---

## 🧪 Tests (required)
- **Unit-Tests:** Happy Path, Validierungsfehler, Dependency-Timeout → Retry
- **Contract-Tests:** Rückgabetypen, Iteration, Feldnamen, HTTP-Schema
- **E2E (mind. 1 Flow):** Eingabe → Worker/Router → DB/API-Ergebnis
- **Negative/Fehlerfälle:** Exhaustiv
- **Snapshot/Golden** (falls sinnvoll): Schemata/Antworten
- **Coverage-Ziel:** ≥ 85 % in geänderten Modulen
- **Stubs/Mocks:** Externe Dienste (Spotify/Plex/slskd) mocken

---

## 🧰 Frontend (falls zutreffend)
- **API-Client:** defensive Normalisierung; strikt typisiert
- **UI-Standards:** `docs/ui-design-guidelines.md` einhalten (Farben, Typo, Spacing, Komponenten)
- **TypeScript:** `tsc --noEmit` grün
- **Tests:** `npm test` (Jest/RTL o. ä.)

---

## 📦 CI-Gates (required)
- Backend: `pytest -q`, `mypy app`, `ruff check .`, `black --check .`
- Frontend (falls vorhanden): `npm test`, `tsc --noEmit`
- **OpenAPI-Assertion:** `/openapi.json` entspricht Vertrag
- Pipeline darf nicht brechen; alle Jobs grün

---

## 📎 Dokumentation
- **CHANGELOG.md:** Eintrag mit Was/Warum
- **Migrationshinweis:** falls API-/DB-Vertrag geändert
- **README/Docs:** relevante Abschnitte aktualisieren

---

## Definition of Done (DoD)
- [ ] Alle neuen/angepassten Tests **grün**
- [ ] Lint/Format **sauber** (ruff/black/tsc)
- [ ] **Keine** `BACKUP`-Datei erstellt/angepasst
- [ ] API-Vertrag & OpenAPI **eingehalten**
- [ ] Idempotent & nebenläufig sicher
- [ ] Doku (README/CHANGELOG/Docs) aktualisiert
- [ ] **Keine Secrets** im Code/Repo

---

## Manuelle QA (Beispielschritte)
1. Dev-Stack (`docker compose up`) mit Minimal-ENV starten
2. Endpoint <X> mit Payload A → Ergebnis B erwarten (HTTP + Body)
3. Fehlerfall (Bad Input/Timeout) simulieren → passender Fehlercode + Log
4. Idempotenz testen (erneut ausführen) → keine Duplikate, konsistenter Zustand

---

## PR & Commits
- **Conventional Commits:** `feat: …` / `fix: …` / `docs: …` / `test: …` / `chore: …`
- **PR-Beschreibung MUSS enthalten:**
  - Kurzfassung (Was/Warum)
  - Änderungen an Dateien (Neu/Geändert/Gelöscht)
  - Migrationshinweise (falls zutreffend)
  - Testnachweise (Logs/Screens)
  - Risiken/Limitierungen
  - Verweis auf **AGENTS.md**-Konformität

---

## Offene Fragen
- <Liste spezifischer Unklarheiten, die vor Umsetzung geklärt werden sollen>

---

## Mini-Beispiel (ausgefüllt)
- **In Scope:** `POST /feature/do-thing` + Worker-Hook + DB-Feld `thing_status`
- **Out of Scope:** Frontend-UI
- **API:** `POST /feature/do-thing` → 202; `GET /feature/status/{id}` → 200/404
- **DB:** `thing_status TEXT DEFAULT 'pending'`
- **ENV:** `THING_TIMEOUT_MS=15000`
- **Retry:** max 3, Backoff 0.5×2^n, Jitter ±20 %
- **Tests:** success, validation error, dependency timeout→retry→success
- **DoD:** alle CI-Gates grün; Doku aktualisiert; idempotent; keine BACKUP
