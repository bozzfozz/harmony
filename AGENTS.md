# AGENTS.md — Neutrale Richtlinien für Agenten und Menschen

Ziel: Einheitliche, sichere und nachvollziehbare Beiträge von Menschen und KI-Agenten für Software- und Wissensprojekte.

## 1. Geltungsbereich und Rollen
- Agent: Automatisierter Beitragender, deterministisch und auditierbar.
- Maintainer: Review, Freigabe, Sicherheit.
- Contributor: Menschliche Beitragende.

## 2. Leitprinzipien
- Klarheit: Explizite Absichten, kleine Schritte, überprüfbare Effekte.
- Simplicity First: Einfache, gut erklärbare Lösungen statt cleverer Komplexität.
- Reproduzierbarkeit: Gleicher Input führt zu gleichem Output.
- Nachvollziehbarkeit: Lückenlose Historie; ADRs für nicht-offensichtliche Entscheidungen.
- Qualität vor Umfang: DRY, KISS, keine toten Strukturen.
- Sicherheit: Least-Privilege, keine Secrets im Repo.
- Kontinuierliche Verbesserung: Dieses Dokument ist lebend.

## 3. Arbeitsablauf (End-to-End)
1. Issue: Problem, Nutzen, Akzeptanzkriterien, Risiken, Done-Definition.
2. Branching: type/short-topic, z. B. feat/add-login, fix/restore-tests. Ein Branch = ein kohärentes Ziel.
3. Commit Hygiene:
   - Conventional Commits: feat, fix, docs, test, chore.
   - Ein Commit pro fokussierter Änderung. Beschreibe Was, Warum, Scope.
   - Beispiel: feat/add-auth: implement token-based login flow.
4. PR-Disziplin:
   - Klein und fokussiert. Issue referenzieren. TASK_ID im Titel und im Body.
   - Erkläre was und warum, inkl. Testnachweisen.
5. Review: Zwei-Augen-Prinzip bei risikoreichen Änderungen.
6. CI-Quality Gates: Lint, Typen, Tests, Security-Scans müssen grün sein.
7. Merge: Squash-Merge bevorzugt. CHANGELOG pflegen.
8. Release: SemVer, Tags, Release-Notes, Rollback-Plan.
9. Post-merge: Monitoring, Metriken, Incident-Prozess.

## 4. Qualitätsstandards
- Coding: PEP 8, Type Hints, Docstrings (PEP 257), keine Magic Numbers, klare Fehlerbehandlung.
- Design-Prinzipien: Konsistente Struktur; Namenskonventionen (snake_case, PascalCase, kebab-case) einhalten; Duplikate vermeiden; Architektur respektieren.
- Testing Expectations:
  - Relevante Suites vor jedem Commit/PR ausführen.
  - Neue Features/Fixes erfordern neue Unit- und Integrationstests.
  - Coverage nicht senken ohne Plan zur Wiederherstellung.
- Quality Gates & Tools:
  - Python: ruff oder flake8, black, isort, mypy.
  - JS/TS (falls vorhanden): eslint, prettier.
  - Lint-Warnungen beheben, toten Code entfernen.

## 5. Prompt- und Agent-Spezifika
- Prompt-Design: Ziel, Eingaben, Ausgaben, Constraints, Abbruchkriterien; Idempotenz; Trennung Instruktion/Daten.
- Konfiguration: Prompts versionieren unter prompts/<name>@vX.Y.Z.md; Parameter und Limits (Timeout, Retries, Rate-Limits) deklarieren.
- Werkzeugnutzung: Nur freigegebene Tools; Minimalrechte; auditierbare Aufrufe; Schreibzugriff auf alle Repository-Pfade; Schutzregeln siehe §19 Scope-Guard und §15 Prohibited.
- Beweise/Logs: Eingaben-Hash, Artefakt-Hashes, Laufzeit, Retries, Exit-Status; keine personenbezogenen Daten.
- AI-spezifische Verantwortlichkeiten:
  - AI-generierter Code ist vollständig, ausführbar, mit bestandenen Tests.
  - Human Maintainer Review ist vor Merge obligatorisch.

## 5.1 Codex Write Mode – Vollzugriff (Default)
**Modus:** Implement (Standard)

**Rechteumfang:**
- Schreibzugriff auf **alle Pfade** im Repository (Erstellen/Ändern/Löschen von Dateien, Reorganisation).
- Branch- und PR-Erstellung jederzeit erlaubt; Direkt-Push auf `main` nur, wenn Repo-Policy es zulässt (empfohlen: Branch + PR).
- Ausführung üblicher Build-/Test-/Lint-/Tool-Befehle ist erlaubt.

**Pflichten & Grenzen:**
- **Keine Secrets** oder Zugangsdaten in den Code/Repo schreiben (§6).
- **Prohibited** (§15) bleibt verbindlich (keine `BACKUP`-/Lizenz-Dateien anfassen).
- **Scope-/Clarification-Regeln** (§19) anwenden: Bei Unklarheit Draft-PR mit „Clarification Request“.
- **Commit-/PR-Standards** (§18) einhalten (Conventional Commits, TASK_ID, Testnachweise).
- **Qualitätsgates** (§14) sind Merge-Gates. Schreiben bleibt erlaubt, Merge nur bei erfüllten Gates oder expliziter Maintainer-Freigabe.

**Empfohlener Flow:**
- Feature-Branch (`feat/<topic>`), kleine Commits, PR mit Task-Referenz und Testnachweisen.
- Keine direkten API-/DB-Breaking-Changes ohne dokumentierte Migration (§7) und Maintainer-Bestätigung.

## 5.2 Fast-Track-Modus (Implement Priority)
**Auto-FAST-TRACK:** Für Tasks mit `TASK_ID`-Präfix **`CODX-ORCH-*`** gilt implizit `FAST-TRACK: true`. Codex darf Dateien anlegen/ändern/löschen, Tests und Snapshots aktualisieren sowie PRs eröffnen, **ohne zusätzliche Freigabe**. **CI bleibt Merge-Gate.**

**Gültigkeit & Grenzen:**
- Scope- und Clarification-Regeln (§19) bleiben anwendbar; nur der Freigabe-Check entfällt.
- Sicherheits- und Compliance-Vorgaben (§6, §15) gelten unverändert.
- Maintainer können den Modus durch Task-Kommentar widerrufen; der Widerruf ist in der Task-Beschreibung zu dokumentieren.

## 6. Daten, Geheimnisse, Compliance
- Secrets: Niemals im Code oder Commit; Secret-Manager nutzen; Rotation dokumentieren.
- Security-Scanner: Python bandit; JS/TS npm audit oder Äquivalent. Findings adressieren.
- Datenschutz: Datenminimierung, Zweckbindung, Löschkonzepte.
- Lizenzen und Header: Drittcode nur mit kompatibler Lizenz. Bis zur Lizenzwahl: Datei-Header "Copyright <year> Contributors".

## 7. Release, Rollback, Migration
- SemVer: MAJOR inkompatibel, MINOR Feature, PATCH Fix.
- Migrationen: Reversibel, Dry-Run, Backups.
- Rollback: Definierter Trigger, RTO/RPO, automatisiertes Zurücksetzen.

## 8. Incident-Prozess
1. Erkennen: Monitoring, Alerts, SLO/SLI.
2. Eindämmen: Feature-Flag oder Rollback.
3. Beheben: Patch mit Tests.
4. Postmortem: Ursachen, Maßnahmen, Fristen.

## 9. Checklisten
PR-Checkliste:
- [ ] Issue verlinkt und Beschreibung vollständig
- [ ] Kleine, fokussierte Änderung
- [ ] TASK_ID im Titel und PR-Body (verweist auf docs/task-template.md)
- [ ] AGENTS.md gelesen & Scope-Guard bestätigt
- [ ] Keine Secrets, `BACKUP`- oder Lizenz-Dateien verändert
- [ ] Tests/Linting grün (`pytest`, `mypy`, `ruff`, `black --check`) oder Ausnahme begründet
- [ ] Security-Scan ohne Blocker
- [ ] OpenAPI/Snapshots aktualisiert (falls API betroffen)
- [ ] Doku-/ENV-Drift behoben (README, CHANGELOG, ADRs)
- [ ] Rollback-Plan vorhanden
- [ ] Testnachweise dokumentiert (Logs, Screens, Coverage)

Agent-Ausführung:
- [ ] Eingaben validiert, Schema geprüft
- [ ] Schreibpfade erlaubt
- [ ] Rate-Limit und Retry-Policy gesetzt
- [ ] Logs ohne personenbezogene Daten
- [ ] Artefakte gehasht und abgelegt

## 10. Vorlagen
Issue:
- Titel: kurz, präzise
- Beschreibung: Problem, Nutzen
- Akzeptanzkriterien: messbar
- Risiken/Annahmen: Stichpunkte
- Fertig wenn: Kriterien

PR-Beschreibung:
- Änderung: was, warum
- Scope: module/paket
- Breaking changes: ja/nein und welche
- Tests: neu/angepasst, Abdeckung, Testnachweise
- Security: Scan-Ergebnis, Secrets
- Rollback: Strategie
- TASK_ID: z. B. TASK-123 (siehe docs/task-template.md)

ADR (Kurzform):
- Titel, Datum, Kontext, Entscheidung, Alternativen, Folgen

## 11. Durchsetzung
- CI-Gates erzwingen Lint, Typen, Tests, Security-Scans.
- Schreibrechte von Codex sind nicht CI-gekoppelt; CI bleibt ausschließlich Merge-Gate. Auto-FAST-TRACK-Tasks (`CODX-ORCH-*`) folgen derselben Regel; PR-/Branch-Flow empfohlen.
- Pre-Commit Hooks empfohlen: ruff, black, isort.
- PR wird geblockt, wenn TASK_ID oder Testnachweise fehlen.
- Merge nur bei erfüllten Checklisten.
- Wiederholte Verstöße führen zu Review-Pflicht und ggf. Rechtemanagement.

## 12. Task-Template-Pflicht
Alle Aufgaben **müssen** auf Basis von `docs/task-template.md` erstellt, umgesetzt und reviewed werden.

- Abweichungen sind nur mit ausdrücklicher Maintainer-Freigabe zulässig und müssen im PR begründet werden.
- PR-Beschreibungen füllen alle Template-Sektionen (Scope, API-Vertrag, DB, Konfiguration, Sicherheit, Tests, DoD) nachvollziehbar aus.
- TASK_ID bleibt im Titel und Body verpflichtend und verweist auf das ausgefüllte Template.

## 13. ToDo-Pflege (verbindlich)
Nach Abschluss **jedes Tasks** ist `ToDo.md` zu pflegen.

- Erledigte Punkte entfernen oder abhaken, Folgeaufgaben dokumentieren.
- PR-Beschreibung enthält einen expliziten **Nachweis des ToDo-Updates** (z. B. Link/Commit-Hash, Screenshot des Boards).
- Ohne ToDo-Nachweis erfolgt kein Merge.

## 14. Completion Gates (Pflicht)
Vor dem Merge müssen alle relevanten Checks erfolgreich durchlaufen. Gates prüfen Qualität; fehlgeschlagene Gates dürfen das Schreiben nicht verhindern, wohl aber den Merge.

- Backend: `pytest -q`, `mypy app`, `ruff check .`, `black --check .`.
- Frontend (falls vorhanden): `npm test`, `tsc --noEmit`.
- OpenAPI-Gate: Änderungen am Schema geprüft; API-Verträge (Statuscodes, Strukturen) eingehalten.
- Coverage-Ziel: ≥ 85 % in geänderten Modulen oder begründete Ausnahme im PR.

## 15. Prohibited
- Keine `BACKUP`-Dateien anlegen oder verändern.
- Keine Lizenzdateien ändern oder hinzufügen ohne Maintainer-Freigabe.
- Keine Secrets oder Access-Tokens im Repo ablegen (nur über ENV/Secret-Store).
- Keine stillen Breaking Changes; nur mit Major-Bump und dokumentierter Migration zulässig.

## 16. Frontend-Standards
- `docs/ui-design-guidelines.md` ist verbindlich (Farben, Typografie, Spacing, Komponenten, Interaktionen).
- TypeScript strikt: `tsc --noEmit` muss erfolgreich sein; API-Clients defensiv implementieren.
- UI-Änderungen nutzen die vorgegebenen Komponentenbibliotheken (z. B. shadcn/ui, Radix) und etablierten Patterns (Tabs, Cards, Toasts).

## 17. Backend-Standards
- Public-API-Verträge dokumentieren; Fehlercodes: `VALIDATION_ERROR`, `NOT_FOUND`, `RATE_LIMITED`, `DEPENDENCY_ERROR`, `INTERNAL_ERROR`.
- Idempotenz und Nebenläufigkeit sicherstellen (Queues, Locks, Backoff-Strategien).
- Logging strukturiert mit `event`, `entity_id`, `status`, `duration_ms`; Fehlermeldungen aussagekräftig halten.

## 18. Review & PR
- Commits folgen Conventional-Commit-Standards (feat/fix/docs/test/chore).
- PR-Beschreibung MUSS enthalten: Was/Warum, Dateiänderungen (Neu/Geändert/Gelöscht), Migrationshinweise, Testnachweise (Logs/Screens), Risiken/Limitierungen, Verweis auf AGENTS.md/Template-Konformität sowie den **Nachweis des ToDo-Updates**.
- Review achtet auf vollständige Template-Erfüllung und Einhaltung aller Completion Gates.

## 19. Initiative-, Scope- und Clarification-Regeln <a id="initiative-scope-clarification"></a>

**Quick Reference:** Prüfe vor jeder Änderung `Zulässige Initiative` → `Scope-Guard` → `Clarification-Trigger` → `Commit-/PR-Standards` → `CI-/OpenAPI-Gates` → `Beispiele (Do/Don't)`.

### Zulässige Initiative (DRIFT-FIX) <a id="zulassige-initiative"></a>

**Darf ohne Rückfrage (`MAY`, Commits optional mit `[DRIFT-FIX]` taggen):**
- Defekte Tests, Lints oder Typprüfungen reparieren, solange Ursache eindeutig ist und **keine** Public-API beeinflusst wird.
- Offensichtliche Lint-/Type-/Import-Fehler oder fehlerhafte Pfade beheben; tote Importe entfernen.
- Doku-Drift in README/ENV/OpenAPI-Beispielen korrigieren, wenn die Codequelle eindeutig ist.
- Snapshots/OpenAPI regenerieren, sofern der veröffentlichte Vertrag unverändert bleibt.
- Vorhandene Migrationen verdrahten oder ausführen, **wenn** die Aufgabe es explizit verlangt.

**Mini-Checkliste (nur wenn alle Kästchen `true` → Initiative zulässig):**
- [ ] Änderung ist rein mechanisch (keine neue Business-Logik).
- [ ] Öffentliche APIs, DB-Schemas und Konfiguration bleiben identisch.
- [ ] Quelle der Wahrheit ist eindeutig (kein Ratespiel, keine Divergenz zu Docs/Code).

**Darf nur mit Task-Update oder Freigabe nach Clarification:**
- Schema-/API-Änderungen, neue Endpunkte oder zusätzliche Felder.
- Migrationslogik, die Daten manipuliert oder Verlust riskieren könnte.
- UI-Flows, Feature-Flags oder Konfiguration mit Nutzerwirkung.
- Änderungen mit potenziellem Performance- oder Semantik-Einfluss.

### Scope-Guard <a id="scope-guard"></a>

**MUST NOT:**
- `BACKUP`-, `LICENSE`- oder andere geschützte Dateien anfassen.
- Secrets, Tokens oder personenbezogene Daten ins Repository schreiben.
- Public-APIs brechen, DB-Schemata ohne Migration ändern oder Datenverlust riskieren.

**MUST:**
- Migrationen idempotent halten; Rollback-Pfade dokumentieren.
- Feature-Flags mit sicheren Defaults versehen (failsafe/off), wenn sie Teil des Tasks sind.
- OpenAPI-Spezifikation, Tests und Dokumentation synchron halten.

**Scope-Checkliste (vor jedem Commit prüfen):**
- [ ] Geänderte Pfade liegen vollständig innerhalb des Task-Scopes.
- [ ] Kein neuer oder geänderter Contract ohne explizite Freigabe.
- [ ] Secrets/geschützte Dateien unverändert.

### Clarification-Trigger (zwingend nachfragen) <a id="clarification-trigger"></a>

Starte eine Rückfrage, wenn **mindestens einer** der Punkte zutrifft:
- Task widerspricht bestehendem Code, Dokumentation oder den Scope-Guards.
- Zielmetrik, gewünschtes Verhalten oder benötigte ENV/Secrets sind unklar oder fehlen.
- Die Umsetzung würde Public-API, DB-Schema oder migrationsrelevante Daten berühren.
- Tests verlangen Verhalten, das in keinem Vertrag dokumentiert ist.
- Externe Abhängigkeit oder Integrationsdetail (z. B. slskd/Spotify) ist nicht spezifiziert.

**Hinweis Auto-FAST-TRACK (`CODX-ORCH-*`):** Minimal-invasive, reversible Änderungen dürfen ohne Rückfrage erfolgen. Bei potentiellen Contract-, Schema- oder Sicherheitsänderungen ist weiterhin eine Draft-PR als „Clarification Request“ zu eröffnen.

**Clarification-Prozess:**
1. PR in Draft setzen und Titel `Clarification Request: <TASK_ID>` nutzen.
2. Inhalt strukturieren: **Beobachtung**, **Blocker (Logs/Diffs)**, **Minimalvorschlag** (reversibel), **Impact**.
3. Label `needs-owner-decision` setzen und auf Antwort warten. Ohne Freigabe **keine** Abweichung umsetzen.

### Commit-/PR-Standards <a id="commit-pr-standards"></a>

**Commits:**
- Conventional Commits nutzen (`feat:`, `fix:`, `docs:`, `test:`, `chore:`) optional mit Scope (`feat(api): …`).
- TASK-ID anfügen (`… [CODX-123]`), `[DRIFT-FIX]` bei reinem Drift-Fix optional ergänzen.
- Ein Commit = ein fokussiertes Thema mit kurzer „Was/Warum“-Beschreibung.

**PR-Beschreibung (Pflichtinhalte):**
- Kurzfassung (Was/Warum) und Risiko/Limitierungen.
- Änderungen an Dateien (Neu/Geändert/Gelöscht) als Liste.
- Testnachweise mit Befehlen/Logs/Screenshots.
- Verweis auf AGENTS.md-Konformität und ggf. OpenAPI-/ENV-Updates.

**PR-Checkliste (muss vollständig im PR abgehakt sein):**
- [ ] AGENTS.md gelesen und Scope-Guard geprüft.
- [ ] Keine Secrets/`BACKUP`/Lizenzdateien verändert.
- [ ] Tests grün (`pytest`, `mypy`, `ruff`, `black --check`) bzw. begründete Ausnahme dokumentiert.
- [ ] OpenAPI/Snapshots aktualisiert, falls API betroffen.
- [ ] Doku-/ENV-Drift geprüft und behoben.

### CI-/OpenAPI-Gates <a id="ci-openapi-gates"></a>

**MUST PASS (lokal oder CI):**
- `pytest`
- `mypy`
- `ruff`
- `black --check`

**Zusätzliche Gates (nur bei Relevanz, dürfen nicht rot sein):**
- OpenAPI-Snapshot (`/openapi.json`) aktualisieren, wenn Verträge sich ändern.
- Beispiel-Responses und Doku synchronisieren (README/Docs, API-Referenzen).
- `scope_guard`, `api_guard`, `db_guard`, `deps_guard` dürfen keine Blocker melden.

### Beispiele (Do/Don't) <a id="initiative-examples"></a>

| Do | Don't |
| --- | --- |
| ENV-Variable in README ergänzen, wenn `app/config.py` die Quelle klar vorgibt. | Schema-Feld „klein“ erweitern ohne Migration oder Task-Freigabe. |
| Fehlenden Test importieren und Pfad korrigieren, weil `pytest` bricht. | Tests löschen oder abschwächen, um CI grün zu bekommen. |
| OpenAPI-Beispiel aktualisieren, wenn Response-Model bereits geändert wurde. | Neue API-Route implementieren, weil sie „praktisch wäre“, ohne Scope-Anpassung. |
| Snapshot-Drift beheben und `[DRIFT-FIX]` dokumentieren. | Feature-Flag-Default ändern, ohne dass der Task dies verlangt. |

### Durchsetzung & Glossar
- PRs, die gegen „MUST NOT“ verstoßen oder Gates reißen, werden nicht gemerged; Wiederholung erfordert Policy-Update.
- **DRIFT-FIX:** kleinste mechanische Korrekturen, die Build/Lint/Tests wiederherstellen, ohne Public Contracts zu ändern.
