# Security

Harmony verfolgt ein Security-by-Default-Konzept. Details zu Profilen, Laufzeit-Overrides und dem automatischen Bandit-Autofix-Workflow findest du in [`docs/security.md`](docs/security.md).

## Automatische Bandit-Autofixes

- Workflow `security-autofix` läuft nächtlich sowie auf internen PRs und behebt Allowlist-Findings (`B506`, `B603/B602`, `B324`, `B306`, `B311`, `B108`).
- Auto-Merge erfolgt ausschließlich bei grünen Quality-Gates (`ruff`, `black`, `isort`, `mypy`, `pytest`, `bandit`) und wenn keine Guards (Public-Contracts, Serialisierung, CLI) ausgelöst werden; andernfalls setzt der Workflow `needs-security-review`.
- Opt-out per Repository-/Org-Variable `SECURITY_AUTOFIX=0`, lokaler Dry-Run über `pre-commit run security-autofix --all-files`.

Weitere Hinweise zu Policies, Guardrails und Reviewer-Checklisten stehen in [`AGENTS.md`](AGENTS.md#26-security-autofix-policy) sowie [`docs/security-autofix-checklist.md`](docs/security-autofix-checklist.md).
