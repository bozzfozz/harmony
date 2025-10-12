# AGENTS.md — Neutrale Richtlinien für Agenten und Menschen

Ziel: Einheitliche, sichere und nachvollziehbare Beiträge von Menschen und KI-Agenten für Software- und Wissensprojekte. Dieses Dokument regelt **Schreibrechte, Scope, Qualität, Sicherheitsvorgaben, Fast-Track**, **ToDo-Pflege** und **Arbeitsabläufe**.

---

## 0. Normativer Rahmen (für 100 % Maschinenverständnis)

### 0.1 Verbindliche Sprache (RFC-2119)
- **MUST / MUSS** = zwingend einzuhalten.
- **SHOULD / SOLL** = empfohlen, Abweichungen sind zu begründen.
- **MAY / DARF** = optional.

### 0.2 Standard-Parameter (Defaults)
- `RUN_MODE ∈ {write, qa_readonly}` — **default=`write`**.
- `SCOPE_MODE ∈ {backend, frontend}` — **default=`backend`** (Details in §19.1).
- `INTENTIONAL_SCHEMA_CHANGE ∈ {0,1}` — **default=`0`**.
- „grün“ bedeutet: jeweils **Exit-Code 0** des genannten Kommandos.

### 0.3 Deterministische Ausführungssequenz (lokal, vor PR) — MUSS
Reihenfolge ist strikt:
1) Build/Lint/Typen (read-only Checks)
2) Tests (Teil-Suite, dann Voll-Suite)
3) Finale Format-Routine (siehe §14)
4) `git diff --exit-code` muss leer sein
5) Doku/CHANGELOG/PR-Text aktualisieren
6) PR erstellen

### 0.4 Exit-Codes (für Guard-Skripte; Tools MAY map to 1 intern)
- `0` OK
- `2` Companion/Tests/Doku fehlen
- `3` Boundary-Verstoß
- `4` Legacy-Treffer
- `5` Junk/Artefakte im Index
- `6` Orphan/Unreferenzierte Produktivdateien
- `7` TODO/FIXME im Produktivcode

---

## 1. Geltungsbereich und Rollen
- **Agent**: Automatisierter Beitragender, deterministisch und auditierbar.
- **Maintainer**: Review, Freigabe, Sicherheit, Releases.
- **Contributor**: Menschliche Beitragende (intern/extern).

## 2. Leitprinzipien
- **Klarheit**: Explizite Absichten, kleine Schritte, überprüfbare Effekte.
- **Simplicity First**: Einfache Lösungen vor cleverer Komplexität.
- **Reproduzierbarkeit**: Gleicher Input ⇒ gleiches Ergebnis.
- **Nachvollziehbarkeit**: Lückenlose Historie; ADRs für nicht-offensichtliche Entscheidungen.
- **Qualität vor Umfang**: DRY, KISS, keine toten Strukturen.
- **Sicherheit**: Least-Privilege, keine Secrets im Repo.
- **Kontinuierliche Verbesserung**: Dieses Dokument ist lebend.

## 3. Arbeitsablauf (End-to-End)
1. **Issue**: Problem, Nutzen, Akzeptanzkriterien, Risiken, Definition of Done.
2. **Branching**: `type/short-topic` (z. B. `feat/add-login`, `fix/restore-tests`); ein Branch = ein kohärentes Ziel.
3. **Commit Hygiene**
   - Conventional Commits: `feat|fix|docs|test|chore`.
   - Ein Commit pro fokussierter Änderung (Was/Warum/Scope).
4. **PR-Disziplin**
   - Klein & fokussiert. Issue referenzieren. **TASK_ID** im Titel/Body.
   - Erkläre Was/Warum inkl. Testnachweisen.
5. **Review**: Zwei-Augen-Prinzip bei risiko-/vertragsrelevanten Änderungen.
6. **Lokale Quality Gates**: `make doctor`, `make all`, `pre-commit run --all-files` und `pre-commit run --hook-stage push` müssen grün sein.
7. **Merge**: Squash-Merge bevorzugt. CHANGELOG pflegen.
8. **Release**: SemVer, Tags, Notes, Rollback-Plan.
9. **Post-merge**: Monitoring, Metriken, Incident-Prozess.

## 4. Qualitätsstandards
- **Coding**: PEP 8, Type Hints, Docstrings (PEP 257), keine Magic Numbers, klare Fehlerbehandlung.
- **Design**: Konsistente Struktur; Namenskonventionen (snake_case, PascalCase, kebab-case); Duplikate vermeiden; Architektur respektieren.
- **Testing**
  - Relevante Suites vor PR ausführen.
  - Features/Fixes ⇒ neue Unit- & Integrationstests.
  - Coverage nicht senken ohne Plan.
- **Quality Tools**
  - Python: `ruff`, `mypy`, `pytest`, `pip-audit`.
  - JS/TS: `eslint`, `prettier`, Build-/Type-Checks.
  - `ruff` übernimmt Formatierung und Import-Sortierung; zusätzliche `isort`-Gates oder Skripte sind **nicht erlaubt**.
- Lint-Warnungen beheben, toten Code entfernen.
- **Konfiguration**: Runtime-Settings ausschließlich über den zentralen Loader in `app.config` beziehen; `.env` ist optional und ergänzt Code-Defaults, Environment-Variablen haben oberste Priorität.

## 5. Prompt- & Agent-Spezifika
- **Prompt-Design**: Ziel, Eingaben, Ausgaben, Constraints, Abbruchkriterien; Idempotenz; Trennung Instruktion/Daten.
- **Konfiguration**: Prompts versionieren unter `prompts/<name>@vX.Y.Z.md`; Parameter & Limits (Timeout, Retries, Rate-Limits) deklarieren.
- **Werkzeugnutzung**: Nur freigegebene Tools; Minimalrechte; auditierbare Aufrufe.
- **Beweise/Logs**: Eingaben-Hash, Artefakt-Hashes, Laufzeit, Retries, Exit-Status; keine personenbezogenen Daten.
- **AI-Verantwortung**
  - AI-Code ist vollständig, ausführbar, **mit bestandenen Tests**.
  - Human-Review vor Merge obligatorisch.

### 5.1 Codex **Write Mode** – Vollzugriff (**Default**)
**Modus**: `RUN_MODE=write` (Standard).  
**Rechte**:
- **Schreibzugriff auf alle Pfade** im Repository (Erstellen/Ändern/Löschen/Reorganisation).
- Branch/PR jederzeit erlaubt; Direkt-Push auf `main` nur falls Repo-Policy es zulässt (empfohlen: Branch + PR).
- Ausführung üblicher Build-/Test-/Lint-Befehle erlaubt.

**Pflichten & Grenzen**:
- **Keine Secrets** in Code/Repo (§6).
- **§15 Prohibited** gilt (z. B. keine `BACKUP`-/Lizenzdateien anfassen).
- **§19 Scope/Clarification** beachten.
- **§14 Completion Gates** sind Merge-Gates (Schreiben erlaubt, Merge nur grün/mit Freigabe).

### 5.2 Codex **QA Read-only Mode** (opt-in)
**Nur aktiv**, wenn Task/PR **explizit** `RUN_MODE=qa_readonly` setzt.  
Ohne explizites Flag gilt **Write Mode**.

---

## 6. Daten, Geheimnisse, Compliance
- **Secrets**: Niemals im Code/Commit; Secret-Manager nutzen; Rotation dokumentieren.
- **Security-Scanner**: Python `pip-audit`; JS/TS `npm audit` o. Ä.; Findings adressieren.
- **Datenschutz**: Datenminimierung, Zweckbindung, Löschkonzepte.
- **Lizenzen**: Drittcode nur mit kompatibler Lizenz; bis zur Wahl: Datei-Header „Copyright <year> Contributors“.

## 7. Release, Rollback, Migration
- **SemVer**: MAJOR inkompatibel, MINOR Feature, PATCH Fix.
- **Migrationen**: Reversibel, Dry-Run, Backups.
- **Rollback**: Trigger, RTO/RPO, automatisiertes Zurücksetzen.

## 8. Incident-Prozess
1. Erkennen: Monitoring, Alerts, SLO/SLI.
2. Eindämmen: Feature-Flag oder Rollback.
3. Beheben: Patch mit Tests.
4. Postmortem: Ursachen, Maßnahmen, Fristen.

## 9. Checklisten

### PR-Checkliste
- [ ] Issue verlinkt, Beschreibung vollständig.
- [ ] Kleine, fokussierte Änderung.
- [ ] **TASK_ID** im Titel & Body (Template genutzt).
- [ ] **AGENTS.md** gelesen & Scope-Guard bestätigt.
- [ ] Keine Secrets, keine `BACKUP`-/Lizenzdateien verändert.
- [ ] Tests/Lint grün (`pytest`, `mypy`, `ruff format --check`, `ruff check --output-format=github`, `pip-audit`) oder Ausnahme begründet.
- [ ] Security-Scan ohne Blocker.
- [ ] OpenAPI/Snapshots aktualisiert (falls API betroffen).
- [ ] Doku-/ENV-Drift behoben (README, CHANGELOG, ADRs).
- [ ] Rollback-Plan vorhanden.
- [ ] Testnachweise dokumentiert (Logs, Screens, Coverage).
- [ ] **Change-Impact-Scan** (§20) ausgeführt.
- [ ] **ToDo gepflegt – nur falls §25.0 „Erforderlichkeit“ ausgelöst** (Zeitstempel, Priorität, Sortierung, Verweise) **ODER** „No ToDo changes required“ im PR bestätigt.
- [ ] **Wiring-Report** im PR-Body (angepasste Aufrufer/Registrierungen/Exporte).
- [ ] **Removal-Report** im PR-Body (gelöschte Dateien + Begründung).

### Agent-Ausführung
- [ ] Eingaben validiert, Schema geprüft.
- [ ] Passender **SCOPE_MODE** gewählt (§19.1).
- [ ] Retry/Rate-Limits gesetzt.
- [ ] Logs ohne personenbezogene Daten.
- [ ] Artefakte gehasht/abgelegt.

## 10. Vorlagen
- **Issue**: Titel; Beschreibung (Problem/Nutzen); Akzeptanzkriterien; Risiken/Annahmen; DoD.
- **PR**: Was/Warum; Dateiänderungen (Neu/Geändert/Gelöscht); Migrationshinweise; Tests; Risiken/Limitierungen; Verweis auf AGENTS.md/Template; **ToDo-Nachweis (falls erforderlich)**.
- **ADR (Kurz)**: Titel, Datum, Kontext, Entscheidung, Alternativen, Folgen.

## 11. Durchsetzung
- Lokale Gates erzwingen Lint, Typen, Tests und Security-Checks (`make all`, `pre-commit`).
- **Schreibrechte sind nicht Gate-gekoppelt**; Merge nur bei erfüllten Pflichten oder expliziter Maintainer-Freigabe.
- Pre-Commit Hooks **SHOULD**: `ruff-format`, `ruff`, lokale Skripte.
- PR blockiert, wenn **TASK_ID** oder Testnachweise fehlen.

### 11.1 Repository-Guards — MUSS
- `.project-guard.yml` bleibt die zentrale Konfiguration für Companion/Boundary/Legacy/Junk/Orphans/TODO.
- Guard-Skripte laufen lokal (z. B. `python scripts/audit_wiring.py`) und müssen dieselben Exit-Codes wie in §0.4 definieren.
- Harte Verstöße sind nicht bypass-fähig.

## 12. Task-Template-Pflicht
Alle Aufgaben **MÜSSEN** auf Basis von `docs/task-template.md` erstellt, umgesetzt und reviewed werden.
- Abweichungen nur mit Maintainer-Freigabe (im PR begründen).
- PR-Beschreibungen füllen alle Template-Sektionen (Scope, API-Vertrag, DB, Konfiguration, Sicherheit, Tests, DoD) aus.
- **TASK_ID** bleibt im Titel/Body und verweist auf Template.

## 13. ToDo-Pflege (verbindlich, **nicht** als Changelog)
- **Ort:** `ToDo.md` (Repo-Root, Markdown).  
- **Kein Changelog-Ersatz.** ToDo ist **kein** Commit-/PR-Protokoll.  
- **Pflicht nur, wenn §25.0 „Erforderlichkeit“** erfüllt ist. Andernfalls im PR-Body „No ToDo changes required“ bestätigen.

## §14 Code-Style, Lint & Tests — Auto-Fixes (verbindlich)

### Arbeitsablauf des Agents
Finale Code-Aufräumroutine (MUSS)
1) Imports sortieren und Code formatieren:
    ruff format .
    ruff check --select I --fix .
2) Verifizieren, dass keine Änderungen mehr anstehen:
    git diff --exit-code
3) Wenn 2) fehlschlägt:
    Änderungen committen und Schritt 1)–2) wiederholen, bis `git diff` leer ist.
4) Danach Pflichtläufe:
    make dep-sync
    make test
    make fe-build
    make smoke
5) Erst danach Doku/CHANGELOG/PR-Text aktualisieren und Nachweise sichern.

Hinweise
- Formatierung & Import-Policy werden ausschließlich durch Ruff abgedeckt.
- `make all` bündelt Formatierung, Lint, Dependency-Sync, Tests, Frontend-Build und Smoke.

### §14a Ruff Format & Imports
**MUSS**
- Pre-commit Hooks `ruff-format` und `ruff` aktiv halten (`pre-commit install`, `pre-commit run -a`).
- `scripts/dev/fmt.sh` und `scripts/dev/lint_py.sh` vor dem Commit ausführen; keine Commits einreichen, die Drift hinterlassen.

**PR-Checkliste (Ergänzung)**
- [ ] `make doctor` **grün** (Session-Beginn)
- [ ] `make fmt` **grün**
- [ ] `make lint` **grün**
- [ ] `make dep-sync` **grün**
- [ ] `make test` **grün**
- [ ] `make fe-build` **grün**
- [ ] `make smoke` **grün**
- [ ] `pre-commit run --all-files` + `pre-commit run --hook-stage push` dokumentiert

**Lokale Gates (blockierend)**
- `make all`
- `pre-commit run --all-files`
- `pre-commit run --hook-stage push`

**Konfiguration (Referenz)**
- `.pre-commit-config.yaml`: Hooks `ruff-format`, `ruff`
- `pyproject.toml`: `[tool.ruff]` + Lint-/Format-Unterabschnitte

### §14b Pytest Auto-Repair
**Ziel:** Failing Tests automatisch erkennen & beheben, ohne Public-Contracts zu verletzen.

**MUSS**
- Dev-Loop: `pytest --maxfail=1 --lf` → grün ⇒ Vollsuite `pytest -q`.
- Fix-Loop:
  1) Fehler klassifizieren: `ImportError`, `FixtureError`, `TypeError`, `AssertionError`, Snapshot/OpenAPI-Drift, Flakes.
  2) **Auto-Fixes erlaubt**:
     - Fehlende/kaputte Imports, falsche Modul-/Pfad-Namen.
     - Fixture-Reparatur, deterministische Seeds/Clock-Freeze.
     - Offensichtliche Flakes stabilisieren.
     - OpenAPI/Snapshots **nur**, wenn `INTENTIONAL_SCHEMA_CHANGE=1`.
  3) **Nicht erlaubt ohne Task-Freigabe**:
     - Public API/DB-Schema/Fehlercodes ändern.
     - Asserts lockern/entfernen, um „grün“ zu erzwingen.
- Neue/änderte Features ⇒ Tests ergänzen/aktualisieren; Coverage ≥ **85 %** der geänderten Module.

Selektives Testing (schnell)
    pytest $(git diff --name-only origin/main...HEAD | rg '^tests/' -n || true) -q || true
Nachbesserung
    pytest --ff --maxfail=1

PR-Pflichtfeld _Tests_
- Kurzbericht: *Was war kaputt? Ursache? Warum ist der Fix korrekt?* + Links zu Fail-Logs.

Commits
- Auto-Fix: `test: repair <area> (<reason>)`
- Unklare Brüche → Draft-PR „Clarification: <TASK_ID>“.

Reihenfolge
1. Schnelllauf (`--lf`)
2. Volle Suite
3. Finale Routine (`ruff format .`, `ruff check --select I --fix .`, `git diff --exit-code`)

---

## 15. Prohibited
- Keine `BACKUP`-Dateien anlegen oder verändern.
- Keine Lizenzdateien ändern/hinzufügen ohne Maintainer-Freigabe.
- Keine Secrets/Access-Tokens im Repo (nur ENV/Secret-Store).
- Keine stillen Breaking Changes; nur mit Major-Bump + Migration.

## 16. Frontend-Standards
- `docs/ui-design-guidelines.md` verbindlich (Farben, Typografie, Spacing, Komponenten, Interaktionen).
- TypeScript strikt: `tsc --noEmit` grün; API-Clients defensiv.
- UI nutzt vorgegebene Libs/Patterns (z. B. shadcn/ui, Radix).

## 17. Backend-Standards
- Public-API-Verträge dokumentieren; Fehlercodes: `VALIDATION_ERROR`, `NOT_FOUND`, `RATE_LIMITED`, `DEPENDENCY_ERROR`, `INTERNAL_ERROR`.
- Idempotenz & Nebenläufigkeit sicherstellen (Queues, Locks, Backoff).
- Strukturierte Logs: `event`, `component`, `status`, `duration_ms`, `entity_id`, `meta`.

## 18. Review & PR
- Commits nach Conventional-Commit (optional Scope).
- PR MUSS enthalten: Was/Warum, geänderte Dateien (Neu/Geändert/Gelöscht), Migration, Tests/Abdeckung, Risiken/Limitierungen, Verweis auf AGENTS.md/Template, **ToDo-Nachweis (falls erforderlich)**.

## 19. Initiative-, Scope- & Clarification-Regeln

### 19.1 **SCOPE_MODE (binär)**
Wähle **genau einen** Scope pro PR/Task: **`backend`** oder **`frontend`**.

**SCOPE_MODE = backend (Default)**  
Fokus-Pfade (nicht exklusiv):
- `app/**` (core, api, services, integrations, orchestrator, workers, middleware, schemas, utils, migrations)
- `tests/**`, `reports/**`, `docs/**`
- Build/Infra: `pyproject.toml`, `requirements*.txt`, `Makefile`, `Dockerfile*`

**SCOPE_MODE = frontend**  
Fokus-Pfade (nicht exklusiv):
- `frontend/**`, `tests/frontend/**`, `public/**`, `static/**`
- `reports/**`, `docs/**`
- Tooling: `package*.json`, `pnpm-lock.yaml|yarn.lock`, `tsconfig*.json`, `.eslintrc*`, `.prettier*`, `vite|next|webpack|rollup|postcss|tailwind`-Configs

> Änderungen außerhalb der Fokus-Pfade sind zulässig, wenn sie für Build, Tests, Doku oder einen kohärenten Refactor **zwingend erforderlich** sind. §15 gilt immer.

### 19.2 Zulässige Initiative (DRIFT-FIX)
**MAY** (ohne Rückfrage)
- Defekte Tests/Lints/Typen reparieren, sofern **keine** Public-API betroffen.
- Offensichtliche Import-/Pfad-Fehler, tote Importe entfernen.
- Doku-Drift korrigieren, wenn Quelle eindeutig.
- Snapshots/OpenAPI **ohne Vertragsänderung** regenerieren.

**Nur mit Task-Freigabe**
- Schema-/API-Änderungen, neue Endpunkte/Felder.
- Riskante Migrationslogik.
- UI-Flows, Feature-Flags, Konfiguration mit Nutzerwirkung.
- Änderungen mit Performance-/Semantik-Einfluss.

### 19.3 Clarification-Trigger (MUSS nachfragen)
- Widerspruch zwischen Task und Code/Dokumentation/Guards.
- Unklare Zielmetrik/ENV/Secrets.
- Änderung berührt Public-API/DB/Migrationen.
- Tests verlangen undokumentiertes Verhalten.
- Externe Abhängigkeit unspezifiziert.

**Prozess**: Draft-PR „Clarification Request: <TASK_ID>“ → Beobachtung, Blocker (Logs/Diffs), Minimalvorschlag (reversibel), Impact → Label `needs-owner-decision`.

## 20. **Change-Impact-Scan & Auto-Repair (Pflicht)**
Bei Änderungen im gewählten **SCOPE_MODE**:
1. **Suche & Korrektur** von offensichtlichen Fehlern (Build-Fehler, Typfehler, kaputte Imports).
2. **Ref-Update**: Alle Aufrufer/Exports anpassen (Repo-weiter Grep).
3. **Backcompat**: Abgelehnte/verschobene APIs mit Deprecation-Hinweis oder Adapter.
4. **Tests**: Betroffene Tests aktualisieren/ergänzen; Snapshots/Fixtures synchronisieren.
5. **Cross-Module-Verträglichkeit** sicherstellen.
6. **Docs/ENV** synchron halten.

### 20a. Wiring & Removal (verbindlich)
**Ziel:** Nach jeder Änderung ist das System vollständig verdrahtet; nicht mehr benötigte Artefakte sind entfernt.

**MUSS**
1) **Repo-weites Wiring**: Neue/umbenannte Funktion/Klasse/Route/Worker/CLI hat aktualisierte Aufrufer, Registrierungen und Exporte. Keine „stummen“ Entry-Points.
2) **Konsistenter Umbau**: Bei Moves/Ersetzungen sind **alle** Referenzen, Tests, Fixtures, Snapshots, Docs und Makefile-/Skript-Aufrufe angepasst.
3) **Entfernung**: Veraltete Dateien, doppelte Implementierungen, Legacy-Shims und ungenutzte Tests/Dokus werden gelöscht.
4) **Kein toter Code**: Keine ungenutzten Exporte/Imports/Symbole im Produktivcode.

**Pflicht-Checks vor PR**
- Referenzscan:
    git grep -n '<alter_name_oder_namespace>' -- . || true
    git grep -n '<neuer_name_oder_namespace>' -- . || true
- Ruff:
    ruff check --select F401,F841,F822 .
- Vollständiger Build & Tests:
    pytest -q || true
    npm run build || true  # falls Frontend

**PR-Body MUSS enthalten**
- „Wiring-Report“
- „Removal-Report“

**Lokale Gates (Pflicht)**
- `make all`
- `pre-commit run --all-files`
- `pre-commit run --hook-stage push`

## 21. **Auto-Task-Splitting (erlaubt)**
- Agent DARF große Aufgaben in Subtasks/PR-Serie aufteilen (z. B. `CODX-ORCH-084A/B/C`).
- Jeder Subtask enthält Ziel, Scope, DoD, Tests, Rollback.
- Subtasks sollen inkrementell merge-bar sein.

## 22. **FAST-TRACK**
- **Automatisch `FAST-TRACK: true`**, wenn **TASK_ID** eines der Präfixe matcht:
  - `CODX-ORCH-*`
  - `CODX-P1-GW-*`
  - `CODX-P1-SPOT-*`
- Wirkung:
  - Agent DARF ohne weitere Rückfrage implementieren, sofern §15/§19 eingehalten sind und Public-Contracts ungebrochen bleiben.
  - Merge-Gates (§14) bleiben bestehen.

## 23. Beispiele (Do/Don't)

| Do | Don't |
| --- | --- |
| ENV-Variable in README ergänzen, wenn `app/config.py` Quelle klar vorgibt. | Schema-Feld erweitern ohne Migration/Task-Freigabe. |
| Fehlenden Test importieren/Pfad korrigieren, weil `pytest` bricht. | Tests löschen/abschwächen, um Gates grün zu machen. |
| OpenAPI-Beispiel aktualisieren, wenn Response-Model bereits geändert wurde. | Neue API-Route ohne Scope/Task. |
| Snapshot-Drift beheben und `[DRIFT-FIX]` dokumentieren. | Feature-Flag-Default ändern ohne Task. |

## 24. Durchsetzung & Glossar
- PRs, die gegen „MUST NOT“ verstoßen oder Gates reißen, werden nicht gemerged; Wiederholung ⇒ Policy-Update/Restriktion.
- **DRIFT-FIX**: kleinste mechanische Korrekturen zur Wiederherstellung von Build/Lint/Tests, ohne Public-Contracts zu ändern.

---

## 25. **ToDo — Regeln (verbindlich, nicht als Changelog)**

**Zweck:** Zentraler, versionierter Backlog für **fehlende** oder **defizitäre** Funktionen, **technische Schulden**, **Risiken** und **gezielte Verbesserungen**.  
**Ort:** `ToDo.md` (Repo-Root, Markdown).  
**Abgrenzung:** ToDo ist **kein** CHANGELOG, kein Commit-/PR-Protokoll und keine allgemeine Tätigkeitsliste.

### 25.0 Erforderlichkeit (Wann ToDo-Eintrag anlegen?)
**Ein ToDo-Item wird nur erstellt, wenn mindestens eine der Bedingungen erfüllt ist:**
1. Fehlende/platzhalterhafte Implementierung entdeckt (`TODO|FIXME|pass|raise NotImplementedError`, leere Handler/Tests, Mock-Stubs in Produktion).
2. Funktionale Lücke: Feature/Flow faktisch unvollständig.
3. Defekt oder instabile Robustheit.
4. Kontrakt-/Konfig-Drift.
5. Sicherheits-/Compliance-Lücke.
6. Observability-Lücke.
7. Architektur-/Code-Smell mit Folgekosten.
8. Externe Abhängigkeit erfordert Aktion.

**Nicht erzeugen** für:
- Kosmetik (Formatierung, Kommentare).
- Reine Umbenennungen ohne Verhaltensänderung.
- Routine-Doku-Updates ohne inhaltliche Drift.
- Dependency-Bumps ohne Code-Follow-ups.
- „Arbeitstagebuch“.

### 25.1 Eintrags-Format
- **ID**: `TD-YYYYMMDD-XXX`
- **Titel**
- **Status**: `todo|in-progress|blocked|done|wontdo`
- **Priorität**: `P0|P1|P2|P3`
- **Scope**: `backend|frontend|all`
- **Owner**: `codex` | `<Name>`
- **Created_at (UTC)**, **Updated_at (UTC)**, optional **Due_at (UTC)**
- **Tags**
- **Beschreibung**
- **Akzeptanzkriterien**
- **Risiko/Impact**
- **Dependencies**
- **Verweise** (TASK_ID, PR, Commits)
- **Subtasks**

### 25.2 Sortierung & Pflege
- Sortierung nach Priorität, dann `Created_at` aufsteigend.
- Optional Gruppierung nach Status.
- Items ohne Update > 60 Tage ⇒ Review; ggf. `wontdo` statt löschen.

### 25.3 Automatische Pflege (durch Codex)
- Erzeugen nur wenn §25.0 erfüllt; Dedup über (Titel+Tags+Scope).
- Beim Merge passende Items auf `done` setzen; PR/Commit verlinken.
- Wenn §25.0 nicht erfüllt: „No ToDo changes required“ im PR.

### 25.4 Beispiele
**Erzeugen (OK):**
- „Watchlist-Timer verliert Leases bei Langläufern“
- „ProviderGateway: fehlender Retry-Jitter“
- „OpenAPI sagt `200`, Code liefert `202`“

**Nicht erzeugen (NICHT OK):**
- „eslint --fix hat 120 Dateien formatiert“
- „Kommentarstil vereinheitlicht“
- „Paket minor-Bump ohne Code-Follow-ups“