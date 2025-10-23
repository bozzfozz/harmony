# Harmony User Documentation Hub

This hub curates the guides and references that Harmony operators, SREs and
self-hosters need for daily administration. Start here when deploying,
configuring or running the platform in production.

## Orientation & Setup
- [Project README](../../README.md) – product summary, container quickstart and
deployment basics.
- [System overview](../overview.md) – capabilities, request flow and component
interactions.
- [Docker installation](../install/docker.md) – container images, volumes and
port mappings.
- [Configuration reference](../configuration.md) – comprehensive environment and
`harmony.yml` option catalogue.

## Day-to-Day Operations
- [HDM runbook](../operations/runbooks/hdm.md) – recovery procedures and
operational checklists for the Harmony Download Manager.
- [Local operator workflow](../operations/local-workflow.md) – guidance for
running Harmony on a workstation.
- [Security operations](../operations/security.md) – UI session lifecycle, role
permissions and CDN configuration knobs.
- [Database maintenance](../operations/db.md) – SQLite care routines and
migration notes.
- [Dead-letter queue management](../operations/dlq.md) – investigation and
replay workflows for stuck jobs.

## UI Guides
- [Spotify console walkthrough](../ui/spotify.md) – navigation, card
responsibilities and troubleshooting tips for the `/ui/spotify` surface.
- [Soulseek console overview](../ui/soulseek.md) – download queue and
intervention workflows.
- [Content Security Policy guidance](../ui/csp.md) – CSP directives required for
secure UI hosting.

## Security & Compliance
- [Security policy](../../SECURITY.md) – threat model, reporting channels and
hardening checklist.
- [Secure configuration guide](../security.md) – defence-in-depth practices.
- [Secrets management](../secrets.md) – secret storage recommendations and
rotation cadence.
- [Compliance controls](../compliance/hdm_audit.md) – HDM audit trail and
control mapping.
- [FOSS licensing policy](../compliance/foss_policy.md) – approved
third‑party licenses.

## Observability & Health
- [Health endpoints](../health.md) – readiness, liveness and CLI self-checks.
- [Observability playbook](../observability.md) – logging, metrics and alerting
best practices.
- [Error catalogue](../errors.md) – API error semantics and operator responses.

## Integrations & Extensions
- [Spotify OAuth setup](../auth/spotify.md) – configuration steps for PRO mode.
- [Integration notes](../integrations/) – third-party connector walkthroughs and
caveats.
- [Worker orchestration](../workers.md) – lifecycle, concurrency and tuning
knobs for Harmony workers.
- [Worker watchlist](../worker_watchlist.md) – monitoring signals and required
follow-ups.
- [Public API reference](../api.md) – REST endpoints exposed by Harmony.

## Troubleshooting & Support
- [Troubleshooting guide](../troubleshooting.md) – incident triage, recovery
flows and escalation tips.
- [Project status board](../project_status.md) – current initiatives and
operator-impacting updates.

When you introduce new operator-facing documentation, add it to this hub so the
navigation stays current.
