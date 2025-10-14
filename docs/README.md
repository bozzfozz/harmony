# Harmony Documentation Hub

This index consolidates the most relevant guidance for operating, extending and
reviewing Harmony. Use it as the entry point before diving into specific
subsystems.

## Overview & Quickstart
- [Project README](../README.md) – product summary, highlights and quickstart commands.
- [docs/overview.md](overview.md) – system capabilities and end-to-end flow.
- [docs/install/docker.md](install/docker.md) – container deployment instructions.
- [docs/configuration.md](configuration.md) – comprehensive environment variable catalogue.

## Architecture & Design
- [docs/architecture/hdm.md](architecture/hdm.md) – Harmony Download Manager internals.
- [docs/architecture](architecture/) – component diagrams and reference flows.
- [docs/backend-guidelines.md](backend-guidelines.md) – backend coding standards.
- [docs/design-guidelines.md](design-guidelines.md) & [docs/ui-design-guidelines.md](ui-design-guidelines.md) – product and UI principles.
- [docs/frontend](frontend/) – static assets and import-map conventions.

## Operations & Maintenance
- [HDM runbook](operations/runbooks/hdm.md) – operational procedures, recovery steps and checklists.
- [docs/operations/local-workflow.md](operations/local-workflow.md) – local operator workflows.
- [docs/operations/db.md](operations/db.md) & [docs/operations/dlq.md](operations/dlq.md) – datastore and dead-letter queue care.
- [docs/operations/repo_maintenance.md](operations/repo_maintenance.md) – repository quality gates and release duties.
- [docs/troubleshooting.md](troubleshooting.md) – incident triage and recovery hints.

## Security & Compliance
- [SECURITY.md](../SECURITY.md) – threat model, reporting channels and mitigations.
- [docs/security.md](security.md) & [docs/secrets.md](secrets.md) – secure configuration guidance.
- [docs/compliance/hdm_audit.md](compliance/hdm_audit.md) – audit trail for HDM controls.
- [docs/compliance/foss_policy.md](compliance/foss_policy.md) – allowed third-party licenses.

## Observability & Health
- [docs/health.md](health.md) – API health endpoints and CLI self-checks.
- [docs/observability.md](observability.md) – logging, metrics and alerting best practices.

## Development Workflow
- [docs/process/changes_review.md](process/changes_review.md) – historical change review outcomes.
- [docs/task-template.md](task-template.md) – template for new engineering tasks.
- [ToDo.md](../ToDo.md) – backlog of technical follow-ups and risks.

## Testing & Quality
- [docs/testing.md](testing.md) – testing strategy and suites.
- [reports/code_health_report.md](../reports/code_health_report.md) – code quality baseline.

## Integrations & Extensions
- [docs/auth/spotify.md](auth/spotify.md) – Spotify OAuth setup for PRO mode.
- [docs/integrations](integrations/) – integration-specific notes and walkthroughs.
- [docs/workers.md](workers.md) & [docs/worker_watchlist.md](worker_watchlist.md) – worker orchestration and monitoring.

Whenever you add or move documentation, update this hub so contributors can
locate the latest canonical references.
