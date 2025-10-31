# <TITEL – kurz & prägnant>
TASK_ID: CODX-<BEREICH>-<NR>
PRIORITÄT: P0|P1|P2
FAST-TRACK: true|false
SPLIT_ALLOWED: true|false
OWNER: <Name/Team>
DUE: <YYYY-MM-DD>

## 1) Ziel & Nutzen
- **Problem:** <Was ist das Problem?>
- **Zielbild:** <Was soll nachher besser sein?>
- **Erfolgskriterien (messbar):**
  - [ ] <Kriterium 1>
  - [ ] <Kriterium 2>

## 2) Scope
**IN SCOPE**
- <Konkrete Änderungen/Module/Features>

**OUT OF SCOPE**
- <Was ausdrücklich nicht passiert>

**FILES_IN_SCOPE**
- "app/**"
- "docs/**"

**PROHIBITED (hart)**
- "BACKUP/**", "LICENSE", Secrets, stille Breaking-Changes

## 3) Verträge & Kompatibilität
- **Public HTTP-API:** unverändert | Änderungen (Details + OpenAPI-Update erforderlich)
- **DB-Schema:** unverändert | Migration additiv (idempotent, rollback-fähig)
- **Feature-Flags:** <Name>=default OFF/ON (failsafe)
- **Fehlercodes:** VALIDATION_ERROR | NOT_FOUND | DEPENDENCY_ERROR | INTERNAL_ERROR

## 4) Plan / Subtask-Split (falls SPLIT_ALLOWED)
- **max_subtasks:** 3–7
- **Reihenfolge:** analyse → skeleton → impl → gates → docs → cleanup
- **Cluster:** router | services | workers | integrations | frontend
- **Abnahme je Subtask:** kleine PRs mit Tests & DoD

## 5) Implementierungsskizze
- Schritt 1: <Kurze Beschreibung, inkl. Kernfunktionen/Signaturen>
- Schritt 2: <…>
- Schritt 3: <…>

## 6) Konfiguration (ENV) & Defaults
| Variable | Default | Wirkung |
|---|---|---|
| <ENV_NAME> | <Default> | <Beschreibung> |

## 7) Logging & Observability
- **Schema:** `log_event(event, component, status, duration_ms, entity_id?, meta?)`
- **Pflicht-Events:** api.request / api.dependency / worker.job / worker.retry_exhausted
- **Metriken (optional):** Counter/Histogram ableiten

## 8) Tests (Pflicht)
- **Unit:**
  - [ ] <test_case_1>
  - [ ] <test_case_2>
- **Integration/E2E (mit Mocks):**
  - [ ] <flow_case_1>
- **Coverage-Ziel:** ≥ 85 % in geänderten Modulen

## 9) Risiken & Annahmen
- **Risiken:** <Liste>
- **Mitigations:** <Liste>
- **Annahmen:** <Liste>

## 10) Rollback & Migration
- **Rollback:** Git-Revert pro Subtask, keine Datenlöschung
- **Migration:** additiv, idempotent, `DOWN`-Pfad dokumentiert

## 11) Deliverables
- [ ] Code-Änderungen
- [ ] Gates grün (fmt, lint, smoke, audits)
- [ ] Doku: README/CHANGELOG/ADR (falls Architekturentscheidung)
- [ ] Report/Notizen (optional: `reports/`)

## 12) Lokale Gates (Merge-Blocking, Schreiben nicht blockiert)
- `uv run pip-audit --strict`
- `uv run make doctor`
- `pre-commit run --all-files`
- `pre-commit run --hook-stage push`
- Optional: `uv run make release-check` für den vollständigen Aggregationslauf
- OpenAPI-Snapshot aktualisiert (falls API betroffen)

## 13) PR-Checkliste (muss im PR abgehakt sein)
- [ ] TASK_ID im Titel/Body, AGENTS.md befolgt
- [ ] Scope eingehalten, keine verbotenen Dateien
- [ ] Lint + Typen + Smokes grün (oder begründete Ausnahme)
- [ ] OpenAPI/Doku synchron
- [ ] Rollback-Plan dokumentiert

## 14) Hinweise für Codex (Operational)
- **Write-Mode:** Vollzugriff gemäß AGENTS.md §5.1 (alle Pfade außer „Prohibited“)
- **FAST-TRACK:** Falls `true`, darf Codex ohne weitere Rückfragen starten
- **Clarifications:** Nur auslösen, wenn Scope/Contracts unklar oder Breaking-Change unvermeidbar
