# Harmony AI & Engineering Documentation Hub

This hub consolidates the architectural references, coding standards and
workflow guardrails used by Harmony maintainers and AI contributors. Consult it
before changing code, authoring tasks or updating automation policies.

## System Architecture & Domain Knowledge
- [System overview](../overview.md) – end-to-end capabilities and primary flows.
- [Architecture index](../architecture/) – component diagrams and reference
interactions.
- [HDM internals](../architecture/hdm.md) – Harmony Download Manager design and
data movement.
- [High-level architecture brief](../architecture.md) – platform scope and
service boundaries.
- [Public API reference](../api.md) – REST surface area exposed by the backend.

## Development Standards & Design
- [Backend coding guidelines](../backend-guidelines.md) – patterns, limits and
review expectations for Python services.
- [Product & UX design principles](../design-guidelines.md) – decision
frameworks that inform feature work.
- [Code health report](../code_health_report.md) – quality gates and recent
refactors to monitor.
- [Security engineering checklist](../security.md) – defence-in-depth practices
specific to backend development.

## Engineering Workflow
- [Task template](../task-template.md) – required structure for new engineering
work items.
- [Change review log](../process/changes_review.md) – historical review outcomes
and rationale.
- [Project status board](../project_status.md) – roadmap visibility for
in-flight initiatives.
- [Repository maintenance duties](../operations/repo_maintenance.md) – release
checklists and quality gate ownership.
- [Testing strategy](../testing.md) – suites, tooling and coverage expectations.

## Agent & Contributor Guardrails
- [AGENTS operational guidelines](../../AGENTS.md) – mandatory instructions for
automation and human contributors alike.
- [Compliance controls](../compliance/hdm_audit.md) – audit trail for HDM
security measures.
- [FOSS licensing policy](../compliance/foss_policy.md) – dependency approval
matrix and guardrails.

Update this hub whenever you add or relocate engineering-focused documentation
so internal contributors stay aligned.
