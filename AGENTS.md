# AGENTS.md — Neutrale Richtlinien für Agenten und Menschen

**Guiding loop:** *Problem definition → small, safe change → change review → refactor — repeat the loop.*

---

## Quick Rules (1-Pager)

**Mandatory (MUST)**
- Lies relevante Dateien **end-to-end**, inkl. Aufrufer/Referenzen/Tests/Configs, **bevor** du Code änderst.
- Halte Änderungen **klein & fokussiert** (ein Branch/PR = ein Ziel).
- **Keine Secrets** in Code/Commits/Logs; Eingaben validieren, Ausgaben normalisieren/encoden.
- Dokumentiere Annahmen/Entscheidungen im Issue/PR/ADR; vergleiche **mind. 2 Optionen** (Pros/Cons/Risiken).
- Code-Grenzen: Datei ≤ **300 LOC**, Funktion ≤ **50 LOC**, ≤ **5** Parameter, **CC ≤ 10** → sonst **refactor**.
- Neue Features/Fixes **brauchen Tests** (≥1 Happy Path, ≥1 Failure Path). Tests deterministisch & unabhängig.

**Mindset (SHOULD)**
- Denke wie ein Senior: **keine** Schnellschüsse; **simpel vor clever**; Risiken (Nebenläufigkeit/Locks/Backoff) aktiv bewerten.
- Side-Effects an den **Boundary-Layer** isolieren; klare, absichtsverratende Namen.

**Don’ts (MUST NOT)**
- Code ändern ohne den **vollen Kontext** gelesen zu haben.
- Fehler/Warnungen ignorieren, breite `except:` verwenden oder API-Verträge still brechen.
- Vorzeitige Optimierung/Abstraktion oder Hard-Coding von Konstanten/Secrets.

---

## 0. Normativer Rahmen (für 100 % Maschinenverständnis)

### 0.1 Verbindliche Sprache (RFC-2119)
- **MUST / MUSS**, **SHOULD / SOLL**, **MAY / DARF**

### 0.2 Standard-Parameter (Defaults)
- `RUN_MODE ∈ {write, qa_readonly}` — **default=`write`**
- `SCOPE_MODE ∈ {backend, frontend}` — **default=`backend`**
- `INTENTIONAL_SCHEMA_CHANGE ∈ {0,1}` — **default=`0`**
- „grün“ = **Exit-Code 0**

### 0.3 Deterministische Ausführungssequenz (lokal, vor PR) — **MUSS**
1) Build/Lint/Typen (read-only Checks)  
2) Tests (Teil-, dann Voll-Suite)  
3) Finale Format-Routine (§14)  
4) `git diff --exit-code` leer  
5) Doku/CHANGELOG/PR-Text  
6) PR erstellen

### 0.4 Standard-Exit-Codes (für Guards)
`0 OK` · `2 Companion/Tests/Doku fehlen` · `3 Boundary-Verstoß` · `4 Legacy` · `5 Junk` · `6 Orphans` · `7 TODO/FIXME`

---

## 1. Geltungsbereich & Rollen
- **Agent** (automatisiert), **Maintainer**, **Contributor**

## 2. Leitprinzipien
Klarheit · Simplicity First · Reproduzierbarkeit · Nachvollziehbarkeit · Qualität vor Umfang · Sicherheit · Kontinuierliche Verbesserung

## 3. Arbeitsablauf (End-to-End)
Issue → Branching → Commit-Hygiene (Conventional Commits) → PR-Disziplin → Review → Lokale Quality Gates (`make doctor`, `make all`, `pre-commit`) → Merge (Squash bevorzugt) → Release → Post-merge Monitoring

## 4. Qualitätsstandards

### 4.1 Coding & Design
- PEP 8, Type Hints, Docstrings; keine Magic Numbers; klare Fehlerbehandlung.
- **Grenzen** (MUSS): Datei ≤ **300 LOC**, Funktion ≤ **50 LOC**, max. **5** Parameter, **Cyclomatic Complexity ≤ 10**; bei Verstoß: **Refactor**/Split.
- Side-Effects am Rand (I/O/Netz/Global State). Explizite, verständliche Namen.

### 4.2 Code- & File-Referenzregeln (zusammengeführt)
- Vor Änderungen **Definitionen, Referenzen, Call-Sites, Tests, Doku/Config/Flags** auffinden & lesen.
- Vor Symbol-Änderung: Repo-weite Suche (prä/post-Conditions notieren, 1–3 Zeilen Impact-Note im PR).

### 4.3 Testing
- Neues/angepasstes Verhalten ⇒ **neue Tests**; Bugfix ⇒ **Regressionstest** (fail-first).
- **Deterministisch & unabhängig**; externe Systeme durch Fakes/Verträge ersetzen.
- E2E: mind. **1 Happy**, **1 Failure**; Concurrency-Risiken testen.

### 4.4 Clean-Code Regeln
- Eine Funktion – eine Aufgabe; Guard-Clauses; Konstanten symbolisieren; Struktur: **Input → Process → Return**; spezifische Fehler mit klaren Messages; Tests als Anwendungsbeispiele inkl. Rand-/Fehlerfälle.

### 4.5 Quality Tools
- Python: `ruff`, `mypy`, `pytest`, `pip-audit`
- (Ehem. JS/TS nur falls reaktiviert) `eslint`, `prettier`
- `ruff` übernimmt Formatierung & Imports (kein separates `isort`-Gate)

### 4.6 Frontend Supply-Chain (derzeit buildlos)
- Legacy React/Vite entfernt. Wiedereinführung nur über dedizierte SSR-Tasks. `scripts/dev/supply_guard.sh` verhindert eingecheckte Build-Artefakte.

### 4.7 FOSS-Only (lokal)
- **Allow**: MIT, BSD-2/3, Apache-2.0, MPL-2.0, ISC, CC0, Unlicense, Python-2.0, GPL/LGPL/AGPL  
- **Block**: SSPL, BUSL, Elastic 2.0, Redis SA, Confluent Community, Polyform-*, proprietär  
- **Registries**: nur Standard (PyPI, crates, Maven, NuGet, Go). **Keine** privaten Registries/Token by default.  
- Guard: `make foss-scan` (WARN), `make foss-enforce` (STRICT, Exit 12 bei Blockern/Unknown).

### 4.8 Auto-Repair First (verbindlich)
**SCAN → DECIDE → FIX → VERIFY → RE-RUN** (max. 3 Iterationen/Kategorie).  
Lokal (WARN) nie mit Exit≠0 abbrechen; in CI Fix-Commits erlaubt (Branch/PR).

### 4.9 Konfiguration
- Runtime-Settings ausschließlich über zentralen Loader (`app.config`); `.env` optional, **ENV > .env > Defaults**.

---

## 5. Prompt- & Agent-Spezifika
- Prompts versionieren (`prompts/<name>@vX.Y.Z.md`), Parameter/Limits dokumentieren.  
- Werkzeugnutzung minimal & auditierbar.  
- **AI-Code MUSS vollständig, ausführbar und getestet** sein; Human-Review vor Merge.

---

## 6. Daten, Geheimnisse, Compliance (Security)
- **Nie** Secrets in Code/Logs/Tickets; Secret-Manager & Rotation dokumentieren.
- Eingaben **validieren/normalisieren/encoden**; parametrisierte Operationen.
- **Least-Privilege** anwenden; `pip-audit`/Scanner regelmäßig.

---

## 7. Release, Rollback, Migration
SemVer; reversible Migrationen; Rollback-Plan.

## 8. Incident-Prozess
Erkennen → Eindämmen → Beheben → Postmortem

## 9. Checklisten (Auszug)

### 9.1 PR-Checkliste
- Issue verlinkt; **TASK_ID** im Titel/Body; klein & fokussiert  
- Tests/Lint grün (`pytest`, `mypy`, `ruff format --check`, `ruff check`, `pip-audit`)  
- Security-Scan ohne Blocker; OpenAPI/Snapshots aktualisiert  
- Doku/ENV-Drift behoben; Rollback-Plan; Testnachweise  
- **Change-Impact-Scan** & ToDo-Pflege/Bestätigung  
- **Wiring-Report** & **Removal-Report**

### 9.2 Agent-Ausführung
- Eingaben validiert; passender **SCOPE_MODE** (§19.1); Logs ohne PII; Artefakte gehasht

---

## 10. Vorlagen
Issue/PR/ADR-Templates (Kontext, Ziel, DoD, Risiken, Alternativen)

## 11. Durchsetzung
- Lokale Gates erzwingen Lint/Typen/Tests/Security.  
- Pre-Commit Hooks **SHOULD**: `ruff-format`, `ruff`.  
- PR blockiert, wenn **TASK_ID** oder Testnachweise fehlen.

### 11.1 Repository-Guards — **MUSS**
`.project-guard.yml` als Zentralkonfig; identische Exit-Codes wie §0.4.

---

## 12. Task-Template-Pflicht
Alle Aufgaben per `docs/task-template.md`. PRs füllen alle Pflichtsektionen aus.

## 13. ToDo-Pflege (verbindlich, **kein** Changelog)
Ort: `ToDo.md`. Eintrag **nur** bei §25.0-Bedingungen (fehlende Impl., Defekt, Drift, Security, Observability, Smell, externe Abhängigkeit).

---

## §14 Code-Style, Lint & Tests — Auto-Fixes (verbindlich)

### 14.0 Struktur-Limits (wiederholt, **MUSS**)
- **Datei ≤ 300 LOC**, **Funktion ≤ 50 LOC**, **≤ 5 Parameter**, **CC ≤ 10**  
- Bei Verstoß: **aufteilen/refactor**; vor Merge dokumentieren.

### 14.1 Finale Aufräumroutine
1) `ruff format .` → `ruff check --select I --fix .`  
2) `git diff --exit-code` (falls Änderungen → commit & 1–2 wiederholen)  
3) Pflichtläufe: `make dep-sync` · `make test` · `make fe-build` · `make smoke`  
4) Danach Doku/CHANGELOG/PR-Text

### 14.2 Pytest Auto-Repair
- Dev-Loop: `pytest --maxfail=1 --lf` → grün ⇒ `pytest -q`  
- Klassifizieren: Import/Fixture/Type/Assertion/Snapshot/OpenAPI/Flakes  
- **Auto-Fix erlaubt**: offensichtliche Imports/Pfade/Fixtures/Seeds/Flakes  
- **Nicht ohne Freigabe**: Public API/DB/Fehlercodes; Asserts aufweichen  
- Coverage ≥ **85 %** der geänderten Module

### 14.3 Selektives Testing (schnell)
`pytest $(git diff --name-only origin/main...HEAD | rg '^tests/' -n || true) -q || true`

---

## §15 Prohibited
Keine BACKUP-/Lizenzdateien anfassen; keine Secrets; keine stillen Breaking Changes.

## §16 Frontend-Standards
Legacy-Bundle entfernt; SSR-Neuaufbau folgt per Task; keine eingecheckten Artefakte.

## §17 Backend-Standards
Public-API dokumentieren; Fehlercodes (u. a. `VALIDATION_ERROR`, `NOT_FOUND`, `RATE_LIMITED`, `DEPENDENCY_ERROR`, `INTERNAL_ERROR`); Logs strukturiert.

## §18 Review & PR
Was/Warum; Dateien (Neu/Geändert/Gelöscht); Migration; Tests/Abdeckung; Risiken; Verweise auf AGENTS.md/Template; ToDo-Nachweis.

## §19 Initiative-, Scope- & Clarification-Regeln

### 19.1 **SCOPE_MODE (binär)**
**backend** (Default) oder **frontend**; Änderungen außerhalb Fokus nur wenn zwingend.

### 19.2 Zulässige Initiative (DRIFT-FIX)
OK: defekte Tests/Lints/Imports reparieren **ohne** Public-Contract-Änderung; Doku-Drift korrigieren.  
Mit Task-Freigabe: Schema/API/Feature-Flags/Config mit Nutzerwirkung.

### 19.3 Clarification-Trigger (MUSS nachfragen)
Widersprüche/unklare Ziele/Public-API/DB/Secrets/Externe Abhängigkeiten.

---

## §20 Change-Impact-Scan & Auto-Repair (Pflicht)
1) Fehler finden/fixen (Build/Typen/Imports)  
2) Aufrufer/Exports anpassen (repo-weit)  
3) Backcompat sicherstellen (Deprecation/Adapter)  
4) Tests aktualisieren/ergänzen  
5) Cross-Module-Verträglichkeit  
6) Doku/ENV synchron

### 20a Wiring & Removal (verbindlich)
- **Repo-weites Wiring**: alle neuen/umbenannten Entry-Points registriert & referenziert  
- **Konsistenter Umbau**: Referenzen/Tests/Fixtures/Snapshots/Docs/Makefile aktualisiert  
- **Entfernung**: veraltete/doppelte/ungenutzte Artefakte löschen  
- **Kein toter Code** (Ruff: `F401,F841,F822`)

**Pflicht-Checks**: `git grep`, Ruff, `pytest -q`, `make supply-guard`  
**PR-Body**: Wiring- & Removal-Report

---

## §21 Auto-Task-Splitting (erlaubt)
Große Arbeiten in Subtasks/PR-Serie; je Subtask Ziel/Scope/DoD/Tests/Rollback.

## §22 FAST-TRACK
`CODX-ORCH-*`, `CODX-P1-GW-*`, `CODX-P1-SPOT-*` → schneller Implementationspfad (Gates bleiben).

## §23 Beispiele (Do/Don’t)
Do: ENV in README ergänzen, wenn Quelle eindeutig; fehlende Tests/Imports fixen  
Don’t: Tests löschen/verwässern; neue API ohne Scope/Freigabe

## §24 Durchsetzung & Glossar
DRIFT-FIX = kleinste mechanische Korrektur ohne Vertragsänderung.

---

## §25 ToDo — Regeln (verbindlich)
**Erforderlichkeit**: nur bei fehlender Impl., funktionaler Lücke, Defekt, Drift, Security, Observability, Smell, externer Abhängigkeit.  
**Format**: `TD-YYYYMMDD-XXX` · Titel · Status · Priorität · Scope · Owner · Timestamps · Tags · Beschreibung · Akzeptanzkriterien · Risiko · Dependencies · Verweise · Subtasks.  
Pflege: Priorität/Datum; >60 Tage ohne Update ⇒ Review (`wontdo` erwägen).

---

### Changelog-Hinweis
Diese Datei konsolidiert frühere Regeln und die Abschnitte *Mandatory/Mindset/Coding/Testing/Security/Clean-Code/Anti-Pattern* in eine kohärente Richtlinie. Interne Verweise wurden aktualisiert; Struktur-Limits sind in §4.1/§14 verankert.
```0