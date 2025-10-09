# Security-Autofix Reviewer Checklist

Diese Checkliste unterstützt Maintainer:innen und Security-Reviewer:innen dabei, automatisch erstellte Bandit-Autofix-PRs sicher zu beurteilen.

## 1. Vorbedingungen
- [ ] PR-Titel enthält `[CODX-SEC-AUTOFIX-001]` und verweist auf den betroffenen Run (`security/autofix-…`).
- [ ] Labels `security-autofix` (immer) und ggf. `needs-security-review` (wenn Auto-Merge deaktiviert wurde) sind gesetzt.
- [ ] Commit-Messages folgen `security(autofix): <rule-id|multi> remediation [skip-changelog]`.

## 2. Diff-Prüfung
- [ ] Nur Allowlist-Regeln betroffen (`B506`, `B603/B602`, `B324`, `B306`, `B311`, `B108`).
- [ ] Keine Änderungen an Public-APIs, CLI-Flags, Serialisierungsformaten oder persistenten Strukturen.
- [ ] Patches sind mechanisch (keine neue Logik, keine Semantikänderungen außerhalb des Fixers).

## 3. Quality Gates
- [ ] Workflow-Artefakte (`bandit.before.json`, `bandit.after.json`, `autofix_summary.json`, `autofix_summary.md`) überprüft.
- [ ] Bandit-Report nach dem Fix enthält keine offenen Findings.
- [ ] CI-Checks (`isort --check-only`, `mypy`, `pytest`, `pip-audit`) grün; bei Fehlschlag Begründung im PR.

## 4. Guards
- [ ] Bei markierten Guards (z. B. unsichere Shell-Strings, API-Exports) nachvollziehen, ob Auto-Fix korrekt abgebrochen wurde.
- [ ] Falls `needs-security-review` gesetzt ist: Kontext prüfen, ggf. Follow-up-Task oder manuellen Fix beauftragen.

## 5. Rollback & Kommunikation
- [ ] Bei Problemen: Workflow `security-autofix` deaktivieren (`SECURITY_AUTOFIX=0` setzen) und AGENTS.md-Anpassungen dokumentieren.
- [ ] Outcome (Auto-Merge vs. manueller Review) im Security-Kanal bzw. Aufgaben-Tracking festhalten, um Metriken zu aktualisieren.

## 6. Lokaler Reproduktionsweg
- [ ] Optional: `pre-commit run security-autofix --all-files` im Branch ausführen, um den Fixer lokal zu verifizieren.
- [ ] Tests (`pytest`, `bandit`) lokal bestätigen, falls CI-Läufe nicht erreichbar sind.

> Hinweise zu Allowlist/Guards befinden sich in [`AGENTS.md`](../AGENTS.md#26-security-autofix-policy) und [`docs/security.md`](security.md#security-autofix-workflow).
