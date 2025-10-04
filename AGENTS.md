# AGENTS.md — Neutrale Richtlinien für Agenten und Menschen

Ziel: Einheitliche, sichere und nachvollziehbare Beiträge von Menschen und KI-Agenten für Software- und Wissensprojekte. Dieses Dokument regelt **Schreibrechte, Scope, Qualität, Sicherheitsvorgaben, Fast-Track** und **Arbeitsabläufe**.

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
  - Python: `ruff`, `black`, `isort`, `mypy`, `bandit`.
  - JS/TS: `eslint`, `prettier`, Build-/Type-Checks.
- Lint-Warnungen beheben, toten Code entfernen.

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
- **§15 Prohibited** gilt (z. B. keine Lizenz-/BACKUP-Dateien verändern).
- **§19 Scope/Clarification** beachten.
- **§14 Completion Gates** sind Merge-Gates (Schreiben erlaubt, Merge nur grün/mit Freigabe).

### 5.2 Codex **QA Read-only Mode** (opt-in)
**Nur aktiv**, wenn Task/PR **explizit** `RUN_MODE=qa_readonly` setzt.  
Ohne explizites Flag gilt **Write Mode**.

---

## 6. Daten, Geheimnisse, Compliance
- **Secrets**: Niemals im Code/Commit; Secret-Manager nutzen; Rotation dokumentieren.
- **Security-Scanner**: Python `bandit`; JS/TS `npm audit` o. Ä.; Findings adressieren.
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
- [ ] Keine Secrets, keine Lizenz-/`BACKUP`-Dateien verändert.
- [ ] Tests/Lint grün (`pytest`, `mypy`, `ruff`, `black --check`) oder Ausnahme begründet.
- [ ] Security-Scan ohne Blocker.
- [ ] OpenAPI/Snapshots aktualisiert (falls API betroffen).
- [ ] Doku-/ENV-Drift behoben (README, CHANGELOG, ADRs).
- [ ] Rollback-Plan vorhanden.
- [ ] Testnachweise dokumentiert (Logs, Screens, Coverage).
- [ ] **Change-Impact-Scan** (❯ §20) durchgeführt.

### Agent-Ausführung
- [ ] Eingaben validiert, Schema geprüft.
- [ ] Passender **SCOPE_MODE** gewählt (§19.1).
- [ ] Retry/Rate-Limits gesetzt.
- [ ] Logs ohne personenbezogene Daten.
- [ ] Artefakte gehasht/abgelegt.

## 10. Vorlagen
- **Issue**: Titel; Beschreibung (Problem/Nutzen); Akzeptanzkriterien; Risiken/Annahmen; DoD.
- **PR**: Was/Warum; Dateiänderungen (Neu/Geändert/Gelöscht); Migrationshinweise; Tests; Risiken/Limitierungen; Verweis auf AGENTS.md/Template; **ToDo-Update** Nachweis.
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

## 13. ToDo-Pflege (verbindlich)
Nach Abschluss **jedes Tasks** ist `ToDo.md` zu pflegen.
- Erledigte Punkte abhaken/entfernen; Folgeaufgaben dokumentieren.
- PR-Beschreibung enthält **Nachweis des ToDo-Updates** (Link/Hash/Screenshot).

## 14. Completion Gates (Pflicht, Merge-Gate)
- **Backend**: `pytest -q`, `mypy app`, `ruff check .`, `black --check .`.
- **Frontend**: `npm test`, `tsc --noEmit`.
- **OpenAPI-Gate**: Schema/Verträge (Statuscodes/Strukturen) geprüft.
- **Coverage-Ziel**: ≥ 85 % in geänderten Modulen oder begründete Ausnahme.

## 15. Prohibited
- Keine `BACKUP`-Dateien anlegen oder verändern.
- Keine Lizenzdateien ändern/hinzufügen ohne Maintainer-Freigabe.
- Keine Secrets oder Access-Tokens ins Repo (nur ENV/Secret-Store).
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
- PR MUSS enthalten: Was/Warum, geänderte Dateien (Neu/Geändert/Gelöscht), Migration, Tests/Abdeckung, Risiken/Limitierungen, Verweis auf AGENTS.md/Template, **ToDo-Nachweis**.

## 19. Initiative-, Scope- & Clarification-Regeln

### 19.1 **SCOPE_MODE (binär)**
Wähle **genau einen** Scope pro PR/Task: **`backend`** oder **`frontend`**.  
**Default:** `backend`, wenn im Task nicht gesetzt.

**SCOPE_MODE = backend**  
_Fokus-Pfade (nicht exklusiv):_
- `app/**` (core, api, services, integrations, orchestrator, workers, middleware, schemas, utils, migrations)
- `tests/**`, `reports/**`, `docs/**`
- `.github/workflows/**` (Backend-CI)
- Build/Infra: `pyproject.toml`, `requirements*.txt`, `Makefile`, `Dockerfile*`, `ruff.toml`, `mypy.ini`

**SCOPE_MODE = frontend**  
_Fokus-Pfade (nicht exklusiv):_
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
```0