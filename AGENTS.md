# AGENTS.md — Neutrale Richtlinien für autonome KI-Entwicklungsagenten

**Guiding loop:** *Analyse → Plan → Implement → Verify → Refactor → Repeat deterministisch.*

---

## Quick Rules (1-Pager)

**MUST**
- Lies relevante Dateien **end-to-end** inkl. Aufrufer, Referenzen, Tests und Configs, **vor** jeder Änderung.
- Halte Änderungen **atomar**: ein Branch/PR = ein Ziel.
- **Keine Secrets** im Code, in Logs oder Commits; Eingaben validieren, Ausgaben normalisieren und encoden.
- Dokumentiere Annahmen und Entscheidungen im Issue/PR/ADR. Vergleiche mindestens **2 Optionen** (Vor-/Nachteile, Risiken).
- Codegrenzen: Datei ≤ **300 LOC**, Funktion ≤ **50 LOC**, ≤ **5 Parameter**, **CC ≤ 10** → sonst refactor.
- Neue Features/Fixes **müssen Tests haben** (1 Happy Path, 1 Failure Path). Tests deterministisch und unabhängig.

**SHOULD**
- Denke wie ein Senior: simpel vor clever; Risiken (Nebenläufigkeit, Locks, Backoff) aktiv bewerten.
- Side-Effects isolieren; Namen müssen Absicht klar zeigen.

**MUST NOT**
- Ohne Kontextänderung Code modifizieren.
- Warnungen ignorieren, breite `except:` nutzen oder API-Verträge brechen.
- Vorzeitige Optimierung oder Hard-Coding.

---

## §0 Normativer Rahmen

### 0.1 Sprache (RFC-2119)
**MUST**, **SHOULD**, **MAY**.

### 0.2 Standardparameter
`RUN_MODE ∈ {write, qa_readonly}`, Default `write`  
`SCOPE_MODE ∈ {backend, frontend}`, Default `backend`  
`INTENTIONAL_SCHEMA_CHANGE ∈ {0,1}`, Default `0`

### 0.3 Ausführungssequenz
1) Lint/Typen  
2) Tests (Teil-, dann Vollsuite)  
3) Format (`§14`)  
4) `git diff --exit-code` leer  
5) Doku/Changelog  
6) PR erzeugen

### 0.4 Exit-Codes
`0 OK` · `2 Missing Tests` · `3 Boundary Violation` · `4 Legacy` · `5 Junk` · `6 Orphans` · `7 TODO/FIXME`

---

## §1 Rollenmodell (Multi-Agent-System)

### 1.1 Agentenrollen
| Rolle | Funktion |
|-------|-----------|
| **Planner-Agent** | Zerlegt Anforderungen in Teilaufgaben; erstellt Sequenzplan; definiert DoD & Risiken. |
| **Developer-Agent** | Implementiert Code gemäß Plan; erzeugt und aktualisiert Tests. |
| **Reviewer-Agent** | Bewertet Codequalität, Struktur, Komplexität, Dokumentation, Sicherheit. |
| **QA-Agent** | Führt Testausführung, Coverage-Analyse und Regressionen durch. |
| **DevOps-Agent** | Übernimmt Build, Deployment, Metriken, Rollback und Observability. |

### 1.2 Rolleninteraktion
Planner → Developer → Reviewer → QA → DevOps  
Bei Fehlern: Rücksprung zur verantwortlichen Rolle (Automated Feedback Loop).  
Alle Agenten protokollieren Aktionen, Ergebnisse, Exit-Codes und Logs deterministisch.

---

## §2 Leitprinzipien
Klarheit · Nachvollziehbarkeit · Simplicity · Qualität · Sicherheit · Reproduzierbarkeit · Refactor-first.

---

## §3 Entscheidungslogik

1. **Analysephase:** Planner-Agent validiert Anforderungen (§8).  
2. **Planung:** Aufgaben in atomare Einheiten zerlegen.  
3. **Implementierung:** Developer-Agent folgt §4 und §14.  
4. **Review:** Reviewer-Agent prüft Lint, Tests, Sicherheit, Dokumentation.  
5. **QA:** Testausführung (mind. 85 % Coverage).  
6. **Deployment:** DevOps-Agent veröffentlicht nur bei Exit=0.  
7. **Rollback:** Automatischer Rücksprung bei Misserfolg (Exit≠0).  

Entscheidungen basieren auf definierten Exit-Codes. Nur Planner-Agent darf Workflow-Zustände ändern.

---

## §4 Qualitätsstandards

### 4.1 Code & Design
PEP8, Typisierung, Docstrings, Guard Clauses, keine Magic Numbers.  
Grenzen: Datei ≤300 LOC, Funktion ≤50 LOC, ≤5 Parameter, CC≤10.

### 4.2 Referenzregeln
Vor jeder Änderung: Definitionen, Referenzen, Call-Sites, Tests, Configs, Docs lesen.  
Symboländerungen → repoweite Suche, Impact-Notiz im PR.

### 4.3 Runtime Verification
Neue Features → aktualisierte Smoke-/Release-Gates, Bugfix → reproduzierbares Log/Smoke-Evidence.
Mind. 1 Happy + 1 Failure Path in Form nachvollziehbarer Checks oder manueller Protokolle.
Gates deterministisch, unabhängig, Fakes statt echte Systeme.
Smoke-/Health-Gates dokumentieren (`make smoke`, `make ui-smoke`).

### 4.4 Clean Code
Eine Funktion = eine Aufgabe. Struktur: Input → Process → Return.  
Explizite Fehlerbehandlung, klare Namen.

### 4.5 Tools
`ruff`, `mypy`, `pip-audit`, `make release-check`
Optional JS/TS: `eslint`, `prettier`.

---

## §5 Kommunikation & Zusammenarbeit

- Agenten kommunizieren über standardisierte Nachrichtenobjekte:
  - `{role, intent, data, result, status, timestamp}`
- Alle Interaktionen sind **synchronisiert**; keine freie Chat-Kommunikation.
- Reviewer-Agent genehmigt oder verweist zurück mit `status=refactor`.
- Planner-Agent führt Kommunikations-Logs unter `/logs/agents`.

---

## §6 Rückfragen-Handling
Ein Agent MUSS Rückfragen generieren, wenn:
- Anforderungen unklar oder widersprüchlich sind.  
- Public API, DB-Schema oder Sicherheitsaspekte betroffen sind.  
Rückfragen-Form:

Wenn keine Antwort nach Timeout, Entscheidung per konservativer Annahme.

---

## §7 Spezifikationsanalyse
Vor Implementierung: Planner-Agent analysiert Spezifikation, extrahiert:
- Ziele, Constraints, Randbedingungen  
- Risiken, Abhängigkeiten  
- Akzeptanzkriterien (DoD)  
Ergebnis wird als `plan@<task_id>.json` gespeichert.

---

## §8 Sicherheitsrichtlinien
- Keine Secrets, keine Tokens im Repo.  
- Eingaben sanitizen, encoden, validieren.  
- Parametrisierte DB-Zugriffe.  
- Mindestens wöchentlicher Audit via `pip-audit` und CVE-Scan.  
- Least-Privilege-Prinzip.  
- Security-Agent (virtuell) validiert Compliance gegen Policy-Regeln.

---

## §9 Logging & Observability
- Verwende strukturiertes Logging (`JSONL`), keine `print`.  
- Pflichtfelder: `timestamp`, `agent`, `action`, `status`, `exit_code`, `error`.  
- Logs mit Hash signieren (`SHA256`) und archivieren.  
- DevOps-Agent aggregiert Logs für Monitoring und Audit.

---

## §10 Auto-Repair & Self-Healing
**Loop:** Detect → Diagnose → Fix → Verify → Re-Run  
- Max. 3 Versuche pro Kategorie (Lint/Test/Build).  
- Bei anhaltendem Fehler → Escalate an Reviewer-Agent.  
- Fixes nur bei deterministisch reproduzierbaren Fehlern.

---

## §11 Rollback & Recovery
- Alle Deployments sind reversibel (Versioned State).  
- DevOps-Agent führt automatisiertes Rollback bei `Exit>0` aus.  
- Post-Mortem wird als `incident@<timestamp>.md` gespeichert.

---

## §12 Agent Governance
- Nur Planner-Agent darf Subtasks erzeugen oder löschen.  
- Jeder Subtask besitzt eindeutigen `TASK_ID` und Status (`planned`, `in_progress`, `done`, `blocked`).  
- QA-Agent prüft Taskabschluss auf DoD-Erfüllung.  
- Maintainer dürfen Agenten über `agents.yml` konfigurieren, aber nicht direkt überschreiben.

---

## §13 Deterministische Formatierung & Tests
1. `ruff format . && ruff check --fix`
2. `pip-audit`
3. `uv run make release-check`
4. `git diff --exit-code`

---

## §14 Abschlussroutine
- Coverage prüfen (≥85 %).  
- Doku und ADR aktualisieren.  
- Logs und Hashes archivieren.  
- PR mit Change-Impact-Report erstellen.

---

## §15 Glossar
**Planner-Agent:** Planung & Delegation  
**Developer-Agent:** Umsetzung  
**Reviewer-Agent:** Qualität & Sicherheit  
**QA-Agent:** Tests & Validierung  
**DevOps-Agent:** Deployment, Logs, Recovery  
**DoD:** Definition of Done  
**Exit-Code:** numerisches Ergebnis einer Ausführung  
**Refactor:** strukturelle, nicht-funktionale Verbesserung  

---

### Änderungsvermerk
Diese Version integriert Multi-Agentenprinzipien (Planner → Dev → Review → QA → Ops), deterministische Entscheidungslogik, Kommunikationsprotokolle, Sicherheitsrichtlinien und Self-Healing gemäß aktueller Forschung (SWE-Agent, MetaGPT, GPT-Engineer). Alle bisherigen Regeln bleiben aktiv und kompatibel.