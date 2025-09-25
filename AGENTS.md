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
- Werkzeugnutzung: Nur freigegebene Tools; Minimalrechte; auditierbare Aufrufe; Schreibzugriff nur auf erlaubte Pfade.
- Beweise/Logs: Eingaben-Hash, Artefakt-Hashes, Laufzeit, Retries, Exit-Status; keine personenbezogenen Daten.
- AI-spezifische Verantwortlichkeiten:
  - AI-generierter Code ist vollständig, ausführbar, mit bestandenen Tests.
  - Human Maintainer Review ist vor Merge obligatorisch.

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
- [ ] Lint, Typprüfung, Tests grün
- [ ] Security-Scan ohne Blocker
- [ ] Doku aktualisiert (README, CHANGELOG, ADRs)
- [ ] Rollback-Plan vorhanden
- [ ] TASK_ID im Titel und im PR-Body (verweist auf docs/task-template.md)
- [ ] Testnachweise (z. B. pytest -q, Coverage-Summary, relevante Logs)

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
Vor dem Merge müssen alle relevanten Checks erfolgreich durchlaufen.

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
