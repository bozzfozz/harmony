# Auto-Repair Engine Playbook

Die Auto-Repair-Engine orchestriert automatische Korrekturen entlang des Zyklus **SCAN → DECIDE → FIX → VERIFY → RE-RUN**. Dieser Leitfaden beschreibt Log-Formate, Artefakte und Betriebsmodi.

## Reason-Trace-Protokoll

Jede Aktion wird als strukturierter Block auf STDOUT ausgegeben:

```
AUTO-REPAIR | STEP: <SCAN|DECIDE|FIX|VERIFY|RE-RUN|DONE>
AUTO-REPAIR | WHY: <Begründung>
AUTO-REPAIR | COMMAND: <ausgeführter Befehl oder Kontext>
AUTO-REPAIR | RESULT: <Exit-Code oder Status>
AUTO-REPAIR | NEXT: <nächster Schritt>
```

- **STEP** folgt strikt der Reihenfolge SCAN → DECIDE → FIX → VERIFY → RE-RUN → DONE.
- **WHY** dokumentiert faktenbasierte Entscheidungsgründe ohne Interna oder Secrets.
- **COMMAND** beschreibt den ausgeführten Befehl (oder `skip ...`, wenn keine Ausführung stattfand).
- **RESULT** enthält Exit-Codes (`exit=<code>`), `OK`, `WARN` oder Fehlermeldungen.
- **NEXT** signalisiert den nächsten geplanten Schritt oder `NONE` bei Abschluss.

## Artefakt `reports/auto_repair_summary.md`

Jeder Lauf aktualisiert `reports/auto_repair_summary.md` mit:

- Stage-Status (`success`, `warn`, `failed`).
- Aktiver Modus (`STRICT` oder `WARN`).
- Tabelle der erkannten Issues mit Status (`fixed`, `warn`, `error`).
- Optionalen Warnungen je Issue.
- Dokumentierten Kommandos pro Fix (Markdown-Codeblock).

Das Artefakt ist historienlos und beschreibt immer den letzten Lauf. Für Audits kann der Inhalt in CI-Artefakten abgelegt werden.

## Betriebsmodi

- **STRICT** (Default in CI/Docker): Fehler nach allen Fix-Versuchen → Exit-Code ≠ 0.
- **WARN** (`SUPPLY_MODE=WARN` oder `TOOLCHAIN_STRICT=false`): niemals Exit≠0, außer bei Off-Registry- oder P0-Sicherheitsbefunden.
- **CI-Branches** dürfen `ci(auto-fix): ...`-Commits schreiben; `main` nur WARN-Reports.

## Guardrails

- Keine Änderungen an sensiblen Dateien (`LICENSE`, `SECURITY.md`, Backups) ohne menschliche Freigabe.
- Fix-Kommandos laufen mit vorhandenen Least-Privilege-Berechtigungen.
- Logs enthalten keine Secrets; Token/Passwörter werden vor Ausgabe entfernt.

Weitere Details siehe `AGENTS.md`, Abschnitt „Auto-Repair First“.
