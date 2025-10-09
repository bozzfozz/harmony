# AGENTS.md — Neutrale Richtlinien für Agenten und Menschen

Ziel: Einheitliche, sichere und nachvollziehbare Beiträge von Menschen und KI-Agenten für Software- und Wissensprojekte. Dieses Dokument regelt **Schreibrechte, Scope, Qualität, Sicherheitsvorgaben, Fast-Track**, **ToDo-Pflege** und **Arbeitsabläufe**.

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
6. **CI-Quality Gates**: Lint, Typen, Tests, Security-Scans müssen grün sein.
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
  - Python: `ruff`, `black`, `isort`, `mypy`, `pip-audit`.
  - JS/TS: `eslint`, `prettier`, Build-/Type-Checks.
- Lint-Warnungen beheben, toten Code entfernen.
- **Konfiguration**: Runtime-Settings ausschließlich über den zentralen Loader in `app.config` beziehen; `.env` ist optional und ergänzt Code-Defaults, Environment-Variablen haben oberste Priorität.

### 4.1 Ruff Auto-Fix Policy — **verbindlich** (`CODX-RUFF-AUTOFIX-002`)

- **Hooks installieren:** Führt `pip install pre-commit && pre-commit install` aus, bevor ihr Python-Dateien committed. Die verpflichtenden Hooks laufen bei jedem Commit: `ruff check --fix`, `ruff format`, `isort`, `black`.
- **Keine manuellen Fix-Commits:** Führt Ruff-Korrekturen ausschließlich über die Hooks oder `pre-commit run --all-files` aus. Manuelle Formatierungs- oder Lint-Commits gelten als Policy-Verstoß.
- **Pre-commit.ci Auto-Fix:** Der Dienst ist aktiviert und darf fehlende Fixes mit separatem Commit (`chore(pre-commit.ci): apply automated ruff fixes`) ergänzen. Lasst diesen Commit unverändert bestehen; lokale Force-Pushes, die ihn verwerfen, sind zu vermeiden.
- **Ausnahmen:** Rein generierter Code (z. B. `app/migrations/versions/*`, Artefakte aus Codegeneratoren) darf bei Bedarf vom Auto-Fix ausgenommen werden, sofern
  1. der Generator deterministisch dieselbe Ausgabe produziert und
  2. der PR eine kurze Begründung im Beschreibungstext enthält (`Skip Ruff auto-fix: <Grund>`).
  Nutzt in solchen Fällen `SKIP=ruff` gezielt für den Commit und dokumentiert, welcher Generator verantwortlich ist. Reviewer prüfen, dass die Ausnahme eng begrenzt bleibt.
- **Reviewer-Check:** Prüft in jedem PR, ob
  - `pre-commit`-Hooks laufen (`pre-commit.ci` Status oder lokaler Output im PR) und
  - verbleibende Ruff-Findings im CI behoben wurden.
  Offene Ruff-Verstöße oder ausgelassene Hooks blockieren das Merge (`request changes`).
- **CI-Gate:** `.github/workflows/ci.yml` führt `ruff check .` **ohne** `--fix` aus. Bleiben nach Auto-Fixes Verstöße bestehen, schlägt die Pipeline fehl und blockiert den Merge.

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
- [ ] Tests/Lint grün (`pytest`, `mypy`, `ruff`, `black --check`) oder Ausnahme begründet.
- [ ] Security-Scan ohne Blocker.
- [ ] OpenAPI/Snapshots aktualisiert (falls API betroffen).
- [ ] Doku-/ENV-Drift behoben (README, CHANGELOG, ADRs).
- [ ] Rollback-Plan vorhanden.
- [ ] Testnachweise dokumentiert (Logs, Screens, Coverage).
- [ ] **Change-Impact-Scan** (§20) ausgeführt.
- [ ] **ToDo gepflegt – nur falls §25.0 „Erforderlichkeit“ ausgelöst** (Zeitstempel, Priorität, Sortierung, Verweise) **ODER** „No ToDo changes required“ im PR bestätigt.

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
- CI erzwingt Lint, Typen, Tests, Security-Scans.
- **Schreibrechte sind nicht CI-gekoppelt**; Merge nur bei erfüllten Gates/Explizit-Freigabe.
- Pre-Commit Hooks empfohlen: `ruff`, `black`, `isort`.
- PR blockiert, wenn **TASK_ID** oder Testnachweise fehlen.

## 12. Task-Template-Pflicht
Alle Aufgaben **müssen** auf Basis von `docs/task-template.md` erstellt, umgesetzt und reviewed werden.
- Abweichungen nur mit Maintainer-Freigabe (im PR begründen).
- PR-Beschreibungen füllen alle Template-Sektionen (Scope, API-Vertrag, DB, Konfiguration, Sicherheit, Tests, DoD) aus.
- **TASK_ID** bleibt im Titel/Body und verweist auf Template.
- **Ausnahme:** Security-Autofixes aus der Allowlist (§26) dürfen ohne separates Task-Template durchlaufen, wenn die CI-Auto-Merge-Kriterien (Lint/Typing/Tests/Bandit grün, diff mechanisch, keine Public-Contracts) erfüllt sind. Andernfalls gilt die reguläre Template-Pflicht.

## 13. ToDo-Pflege (verbindlich, **nicht** als Changelog)
- **Ort:** `ToDo.md` (Repo-Root).  
- **Kein Changelog-Ersatz.** ToDo ist **kein** Commit-/PR-Protokoll.  
- **Pflicht nur, wenn §25.0 „Erforderlichkeit“** erfüllt ist. Andernfalls im PR-Body „No ToDo changes required“ bestätigen.

## §14 Code-Style, Lint & Tests — Auto-Fixes (verbindlich)

### §14a Code-Style & Auto-Fixes

**Ziel:** Einheitlicher Stil & saubere Imports ohne manuelle Nacharbeit.

**Pflichten (Agent & Humans)**
- Vor jedem Commit **Auto-Fix** ausführen:
  - `ruff check . --fix` (inkl. Import-Sortierung `I`)
  - `ruff format` **oder** `black .`
- Pre-commit Hooks aktiv und genutzt: `pre-commit install` · `pre-commit run -a`
- Keine Commits, die Format/Lint brechen.

**PR-Checkliste (Ergänzung)**
- [ ] `ruff check .` **grün**
- [ ] `ruff format` **oder** `black --check .` **grün**
- [ ] Hooks liefen (Output im letzten Commit oder `pre-commit run -a` verlinkt)

**CI-Gates (blockierend)**
- `ruff check .` (ohne `--fix`)
- `black --check .` (oder `ruff format`-Äquivalent)
- Optional: `pytest -q` vor Merge

**Codex MUSS**
- Vor jedem Push: `ruff check . --fix && (ruff format || black .)`
- Auto-Fixes als separaten Commit: `chore(style): apply ruff/black`
- Minimal-invasiv fixen; keine Funktionslogik verändern.

**Konfiguration (Referenz)**
- `.pre-commit-config.yaml`: Hooks `ruff` (lint+fix) & `ruff-format` (oder `black`)
- `pyproject.toml`:
  - `[tool.ruff] select = ["E","F","I"]; line-length = 88; target-version = "py311"`
  - `[tool.black] line-length = 88; target-version = ["py311"]`

**Hinweise**
- `isort` wird durch `ruff`-Regelgruppe **I** ersetzt.
- Repo-weite Massen-Fixes in eigenem PR: `chore(style): repo-wide auto-format`.
- Security-Autofixes (Bandit-Allowlist gemäß §26) sind zulässig, sofern alle Quality-Gates grün sind und keine Public-Contracts berührt werden.

---

### §14b Pytest Auto-Repair

**Ziel:** Failing Tests automatisch erkennen & beheben, ohne Public-Contracts zu verletzen.

**Pflichten (Agent & Humans)**
- Dev-Loop: `pytest --maxfail=1 --lf` → grün ⇒ vollständige Suite `pytest -q` (in CI).
- Fix-Loop (automatisiert):
  1) Fehler klassifizieren: `ImportError`, `FixtureError`, `TypeError`, `AssertionError`, Snapshot/OpenAPI-Drift, Flakes.
  2) **Erlaubte Auto-Fixes**:
     - Fehlende/kaputte Imports, falsche Modul-/Pfad-Namen.
     - Fixture-Reparatur (Scope, Defaults, Testdaten), deterministische Seeds/Clock-Freeze.
     - Offensichtliche Flakes (Race/Timing/Tempfiles) stabilisieren.
     - OpenAPI/Snapshots **nur**, wenn `INTENTIONAL_SCHEMA_CHANGE=true`; sonst **nicht** anfassen.
  3) **Nicht erlaubt ohne Task-Freigabe**:
     - Public API/DB-Schema/Fehlercodes ändern.
     - Asserts lockern/entfernen, um „grün“ zu erzwingen.
- Neue/änderte Features ⇒ Tests ergänzen/aktualisieren gemäß Akzeptanzkriterien; Coverage ≥ **85 %** der geänderten Module.

**Selektives Testing im Dev-Loop**
- Nur geänderte Tests:  
  `pytest $(git diff --name-only origin/main...HEAD | rg '^tests/' -n || true) -q || true`
- Nachbesserung: `pytest --ff --maxfail=1`

**PR-Pflichtfeld _Tests_**
- Kurzbericht: *Was war kaputt? Ursache? Warum ist der Fix korrekt?* + Links zu Fail-Logs.

**Commits**
- Auto-Fix: `test: repair <area> (<reason>)`
- Unklare/fundamentale Brüche → Draft-PR **Clarification**: „Clarification: <TASK_ID>“ mit Minimalvorschlag.

**Reihenfolge**
1. Style-Auto-Fix (`ruff/black`)
2. Schnelllauf (`--lf`)
3. Volle Suite/CI
```0

## 15. Prohibited
- Keine `BACKUP`-Dateien anlegen oder verändern.
- Keine Lizenzdateien ändern/hinzufügen ohne Maintainer-Freigabe.
- Keine Secrets/Access-Tokens im Repo (nur ENV/Secret-Store).
- Keine stillen Breaking Changes; nur mit Major-Bump + Migration.

**Hinweis:** Mechanische Security-Autofixes aus der Allowlist (§26) gelten nicht als funktionale Änderung und verstoßen nicht gegen diese Verbote, sofern alle Guards eingehalten werden.

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

**SCOPE_MODE = backend (Default für Backend-Aufgaben)**  
Fokus-Pfade (nicht exklusiv):
- `app/**` (core, api, services, integrations, orchestrator, workers, middleware, schemas, utils, migrations)
- `tests/**`, `reports/**`, `docs/**`
- `.github/workflows/**` (Backend-CI)
- Build/Infra: `pyproject.toml`, `requirements*.txt`, `Makefile`, `Dockerfile*`

**SCOPE_MODE = frontend**  
Fokus-Pfade (nicht exklusiv):
- `frontend/**`, `tests/frontend/**`, `public/**`, `static/**`
- `.github/workflows/**` (Frontend-CI)
- `reports/**`, `docs/**`
- Tooling: `package*.json`, `pnpm-lock.yaml|yarn.lock`, `tsconfig*.json`, `.eslintrc*`, `.prettier*`, `vite|next|webpack|rollup|postcss|tailwind`-Configs

> Änderungen **außerhalb** der Fokus-Pfade sind zulässig, wenn sie für Build, Tests, Doku oder einen kohärenten Refactor **zwingend erforderlich** sind. §15 gilt immer.

### 19.2 Zulässige Initiative (DRIFT-FIX)
**Ohne Rückfrage (MAY; optional `[DRIFT-FIX]`)**
- Defekte Tests/Lints/Typen reparieren, sofern **keine** Public-API betroffen.
- Offensichtliche Import-/Pfad-Fehler, tote Importe entfernen.
- Doku-Drift (README/ENV/OpenAPI-Beispiele) korrigieren, wenn Quelle eindeutig.
- Snapshots/OpenAPI **ohne Vertragsänderung** regenerieren.

**Nur mit Task-Update/Freigabe**
- Schema-/API-Änderungen, neue Endpunkte/Felder.
- Migrationslogik mit Datenmanipulation/-verlust-Risiko.
- UI-Flows, Feature-Flags, Konfiguration mit Nutzerwirkung.
- Änderungen mit Performance-/Semantik-Einfluss.

### 19.3 Clarification-Trigger (zwingend nachfragen)
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
5. **Cross-Module-Verträglichkeit**: Sicherstellen, dass angrenzende Bausteine weiterhin funktionieren (z. B. `api` ↔ `services` ↔ `integrations`).
6. **Docs/ENV**: README/Docs/ENV synchron halten.

## 21. **Auto-Task-Splitting (erlaubt)**
- Agent darf große Aufgaben in **Subtasks**/PR-Serie aufteilen (z. B. `CODX-ORCH-084A/B/C`).
- Jeder Subtask enthält Ziel, Scope, DoD, Tests, Rollback.
- Subtasks sollen **inkrementell** merge-bar sein.

## 22. **FAST-TRACK**
- **Automatisch `FAST-TRACK: true`**, wenn **TASK_ID** eines der Präfixe matcht:
  - `CODX-ORCH-*`
  - `CODX-P1-GW-*`
  - `CODX-P1-SPOT-*`
- Wirkung:
  - Agent darf **ohne weitere Rückfrage** implementieren, sofern §15/§19 eingehalten sind und Public-Contracts ungebrochen bleiben.
  - Merge-Gates (§14) bleiben bestehen (Fast-Track beschleunigt Abstimmungen, **hebt Qualitätsschranken nicht auf**).
- Manuelles Override im Task erlaubt: `FAST-TRACK: false`.

## 23. Beispiele (Do/Don't)

| Do | Don't |
| --- | --- |
| ENV-Variable in README ergänzen, wenn `app/config.py` Quelle klar vorgibt. | Schema-Feld „klein“ erweitern ohne Migration/Task-Freigabe. |
| Fehlenden Test importieren/Pfad korrigieren, weil `pytest` bricht. | Tests löschen/abschächen, um CI grün zu bekommen. |
| OpenAPI-Beispiel aktualisieren, wenn Response-Model bereits geändert wurde. | Neue API-Route „weil praktisch“ ohne Scope/Task. |
| Snapshot-Drift beheben und `[DRIFT-FIX]` dokumentieren. | Feature-Flag-Default ändern, ohne dass der Task es verlangt. |

## 24. Durchsetzung & Glossar
- PRs, die gegen „MUST NOT“ verstoßen oder Gates reißen, werden nicht gemerged; Wiederholung ⇒ Policy-Update/Restriktion.
- **DRIFT-FIX**: kleinste mechanische Korrekturen zur Wiederherstellung von Build/Lint/Tests, ohne Public-Contracts zu ändern.

---

## 25. **ToDo — Regeln (verbindlich, nicht als Changelog)**

**Zweck:** Zentraler, versionierter Backlog für **fehlende** oder **defizitäre** Funktionen, **technische Schulden**, **Risiken** und **gezielte Verbesserungen**.  
**Ort:** `ToDo.md` (Repo-Root, Markdown).  
**Abgrenzung:** ToDo ist **kein** CHANGELOG, kein Commit-Protokoll und keine allgemeine Tätigkeitsliste.

### 25.0 Erforderlichkeit (Wann ToDo-Eintrag anlegen?)
**Ein ToDo-Item wird nur erstellt, wenn mindestens eine der Bedingungen erfüllt ist:**
1. **Fehlende/platzhalterhafte Implementierung** entdeckt (`TODO|FIXME|pass|raise NotImplementedError`, leere Handler/Tests, Mock-Stubs in Produktion).
2. **Funktionale Lücke**: Feature/Flow faktisch unvollständig (Kontrakt nicht erfüllt, UI/API/Worker ohne Wirkung).
3. **Defekt oder instabile Robustheit**: Reproduzierbarer Bug, Race Condition, fehlende Idempotenz/Lease/Retry/Timeout.
4. **Kontrakt-/Konfig-Drift**: Code ≠ Dokumentation/OpenAPI/ENV; Breaking ohne Migration.
5. **Sicherheits-/Compliance-Lücke**: Sensitive Daten im Log, Secrets im Code, fehlende Validierung.
6. **Observability-Lücke**: Fehlende Pflichtfelder im Logging-Contract; fehlende Metriken für kritische Pfade.
7. **Architektur-/Code-Smell** mit Folgekosten: Duplikate, Dead Code/Orphans, zyklische Abhängigkeiten, übermäßige Kopplung.
8. **Externe Abhängigkeit** erfordert Aktion: API-Deprecation, Paket-Sicherheitslücke, Rate-Limit-Änderung.

**Nicht erzeugen** für:
- Rein kosmetische Änderungen (Formatierung, Kommentare).
- Reine Umbenennungen ohne Verhaltensänderung.
- Routine-Doku-Updates ohne inhaltliche Drift.
- Dependency-Bumps ohne Code-Follow-ups.
- „Arbeitstagebuch“ (bitte ins PR/CHANGELOG).

### 25.1 Eintrags-Format (pro Item)
- **ID**: `TD-YYYYMMDD-XXX` (laufende Nummer pro Tag).
- **Titel**: Kurz & prägnant.
- **Status**: `todo` | `in-progress` | `blocked` | `done` | `wontdo`.
- **Priorität**: `P0` (kritisch, Ausfall/Sicherheit) / `P1` (hoch, starke Beeinträchtigung) / `P2` (mittel) / `P3` (niedrig).
- **Scope**: `backend` | `frontend` | `all`.
- **Owner**: `codex` | `<Name>`.
- **Created_at (UTC)**: ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`).
- **Updated_at (UTC)**: Bei jeder Änderung aktualisieren.
- **Due_at (UTC, optional)**.
- **Tags**: z. B. `orchestrator`, `router`, `matching`, `observability`.
- **Beschreibung**: Problem, Kontext, gewünschter Zielzustand (3–7 Sätze).
- **Akzeptanzkriterien** (DoD): Messbare Kriterien.
- **Risiko/Impact**: kurz; Backcompat/Performance/Sicherheit.
- **Dependencies**: Blocker/abhängige Issues/Tasks.
- **Verweise**: `TASK_ID`, PR-Links, Commit-Hashes.
- **Subtasks**: Konkrete Schritte (Codex darf automatisch erzeugen/splitten).

### 25.2 Sortierung & Pflege
- **Sortierung**: Nach **Priorität** (P0 → P3), innerhalb Priorität nach **Created_at** aufsteigend.
- **Gruppierung** (optional): Nach **Status** (todo/in-progress/blocked/done/wontdo).
- **Lebenszyklus**: Items ohne Update > 60 Tage → Review; ggf. `wontdo` mit Begründung statt löschen (Historie bewahren).

### 25.3 Automatische Pflege (durch Codex)
- **Erzeugen**: Bei Change-Impact-Scan (§20) ToDo nur anlegen, wenn §25.0 erfüllt; Dedup über (Titel+Tags+Scope).
- **Aktualisieren**: Beim Merge relevante Items auf `done` setzen; **Commit-Hash/PR** in „Verweise“ eintragen.
- **Kein Bedarf**: Wenn §25.0 **nicht** erfüllt, PR-Body mit „No ToDo changes required“ versehen (siehe PR-Checkliste).

### 25.4 Beispiele

**Erzeugen (OK):**
- „Watchlist-Timer verliert Leases bei Langläufern“ (kritische Robustheit).
- „ProviderGateway: fehlender Retry-Jitter“ (Defizit gem. Policy).
- „OpenAPI sagt `200`, Code liefert `202`“ (Kontrakt-Drift).

**Nicht erzeugen (NICHT OK):**
- „eslint --fix hat 120 Dateien formatiert“ (kosmetisch).
- „Kommentarstil vereinheitlicht“ (kosmetisch).
- „Paket minor-Bump ohne Code-Follow-ups“ (kein Handlungsbedarf).

## 26. Security-Autofix-Policy

**Ziel:** Bandit-Findings aus einer eng begrenzten Allowlist deterministisch, testgestützt und nachverfolgbar beheben.

### 26.1 Allowlist (Python-only)

- **B506 (`yaml.load`)** → automatischer Zusatz `Loader=yaml.SafeLoader`, wenn kein Loader-Argument gesetzt ist.
- **B603/B602 (`subprocess.*` mit `shell=True`)** → Umschreiben auf `shell=False` inklusive argv-Splitting, sofern der Kommando-String deterministisch ohne Variableneinbettung ist.
- **B324 (`hashlib.new(name="md5")`)** → Ersetzung durch `sha256` in Test- oder sonstigen Non-Crypto-Kontexten; Guard prüft Pfad/Verwendung.
- **B306 (`tempfile.mktemp`)** → Wechsel auf `NamedTemporaryFile(delete=False).name` (oder äquivalent) ohne zusätzliche Argumente.
- **B311 (`random` für sicherheitsrelevante Tokens/Secrets)** → Ersatz durch `secrets.SystemRandom()`/`secrets`-Utilities in klar identifizierbaren Token/Key-Kontexten.
- **B108 (harte `/tmp`-Pfade)** → Umschreiben auf `tempfile.gettempdir()` plus Pfadaufbau, sofern kein externer Contract betroffen ist.

### 26.2 Denylist (nur manuell)

- **Nicht auto-fixbar:** `B101`, `B102`, `B105`–`B107`, `B307`, `B404` sowie alle Findings außerhalb der Allowlist. Für diese Fälle ist ein regulärer Task inkl. Review vorgeschrieben.

### 26.3 Guards & Governance

- **Public Contracts:** Kein Auto-Fix, wenn betroffene Symbole Teil einer exportierten API, eines CLI-Flags, eines serialisierten Formats oder persistenter Daten sind. Verdachtsfälle führen zu einem PR mit Label `needs-security-review` ohne Auto-Merge.
- **Diff-Scope:** Änderungen bleiben mechanisch (keine Logik-/Verhaltensänderung). Sobald zusätzliche Refactors nötig wären, stoppt der Auto-Fix und verweist auf manuelle Bearbeitung.
- **Tests:** Auto-Merge nur bei vollständig grünen Gates (`ruff`, `black`, `isort`, `mypy`, `pytest`, `bandit`).
- **Bandit-Re-Scan:** Nach jedem Patch muss der Allowlist-Finding verschwinden; neue Findings brechen den Auto-Merge.

### 26.4 Workflow & Commit-Regeln

- **Workflow:** GitHub Action `security-autofix` (PR + nightly) erstellt bei Findings einen Branch `security/autofix-<datum>-<run>` inkl. Artefakten (Bandit vor/nach, Patch-Summary).
- **Commit-Message:** `security(autofix): <rule-id|multi> <kurzbeschreibung> [skip-changelog]`.
- **Labels:** Erfolgreiche Runs erhalten `security-autofix`; bei Guards oder fehlenden Gates zusätzlich `needs-security-review` (kein Auto-Merge).
- **Opt-out:** Repository- oder Organisations-Variable `SECURITY_AUTOFIX=0` deaktiviert den Workflow temporär.
- **Pre-Commit (optional):** `pre-commit run security-autofix --all-files` führt einen Dry-Run (`--check`) aus; `--apply` bleibt CI/Workflow vorbehalten.

### 26.5 Rollback & Monitoring

- **Rollback:** Workflow deaktivieren (`workflow run disable`), Branches löschen, Änderungen an `AGENTS.md` revertieren.
- **Monitoring:** Erste fünf Auto-Fix-PRs manuell beobachten; bei False Positives Allowlist oder Guards nachschärfen.
- **Metriken:** Anzahl automatisch behobener Findings, Verhältnis Auto-Merge vs. Review, Median-Zeit bis Remediation.

---
```0