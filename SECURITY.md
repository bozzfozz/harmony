# Security

Harmony verfolgt ein Security-by-Default-Konzept. Details zu Profilen und Laufzeit-Overrides findest du in [`docs/security.md`](docs/security.md).

## Security-Scans & Policies

- GitHub Actions führt `pip-audit` auf jeder Änderung aus und blockiert den Merge bei bekannten Sicherheitslücken im durch `uv.lock` definierten Stack.
- Weitere Governance- und Review-Vorgaben sind in [`AGENTS.md`](AGENTS.md) dokumentiert.
