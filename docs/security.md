# Security Configuration

Harmony supports security profiles to make it harder to deploy an insecure
configuration by accident. The runtime profile is selected through the
`HARMONY_PROFILE` environment variable. If no profile is provided, the
`default` profile is used.

## Profile defaults

| Profile | `FEATURE_REQUIRE_AUTH` default | `FEATURE_RATE_LIMITING` default |
| ------- | ------------------------------ | -------------------------------- |
| `default`, `dev`, `test`, `staging` | `false` | `false` |
| `prod` (aliases: `production`, `live`) | `true` | `true` |

The defaults shown above are applied only when the corresponding feature flag is
unset. Explicit values supplied via environment variables still take priority.
For example, setting `FEATURE_REQUIRE_AUTH=false` keeps authentication disabled
even when `HARMONY_PROFILE=prod` is active.

## Runtime overrides

The FastAPI middlewares (`ApiKeyAuthMiddleware` and `RateLimitMiddleware`) read
their effective state from `SecurityConfig`. That object tracks both the
profile-default values and any overrides supplied at runtime. Updating
`SecurityConfig.require_auth` or `SecurityConfig.rate_limiting_enabled` toggles
the respective middleware without restarting the application.

When Harmony starts it stores the active `SecurityConfig` instance on the
application state (`app.state.security_config`). Components that need to inspect
the security posture should read from this state to respect both the profile
defaults and dynamic overrides.

## Examples

```bash
# Harden a deployment without managing individual feature flags
export HARMONY_PROFILE=prod

# Override the authentication default for a temporary test window
export FEATURE_REQUIRE_AUTH=false
```

For a complete list of security-related environment variables refer to the
[`README`](../README.md#environment-variables).

## Security autofix workflow

Harmony betreibt einen dedizierten GitHub-Workflow `security-autofix`, der Bandit-Findings aus einer Allowlist automatisiert behebt.

- **Trigger:** läuft nächtlich und auf internen Pull-Requests. Repositories oder Organisationen können den Lauf per `SECURITY_AUTOFIX=0` pausieren.
- **Allowlist:** `B506` (yaml.load ohne Loader), `B603/B602` (subprocess `shell=True`), `B324` (`hashlib.new("md5")` in Tests/Non-Crypto), `B306` (`tempfile.mktemp`), `B311` (`random` für Token/Secrets) und `B108` (harte `/tmp`-Pfade). Alle übrigen Bandit-Regeln landen in manuellen Tasks.
- **Guards:** Kein Auto-Fix bei Public-Contracts (APIs, CLI-Flags, Serialisierung), variablen Shell-Strings oder nicht deterministischen Kontexten. In diesen Fällen erstellt der Workflow eine PR mit Label `needs-security-review` ohne Auto-Merge.
- **Quality Gates:** Jeder Patch durchläuft `ruff`, `black`, `isort`, `mypy`, `pytest` und einen erneuten `bandit`-Scan. Auto-Merge wird nur aktiviert, wenn sämtliche Gates grün sind und der Bandit-Report clean ist.
- **Commit-/PR-Regeln:** Commits folgen dem Schema `security(autofix): <rule-id|multi> remediation [skip-changelog]`, PRs werden unter `[CODX-SEC-AUTOFIX-001]` zusammengefasst und tragen das Label `security-autofix`.
- **Artefakte:** Pre-/Post-Scan, Summary (JSON/Markdown) und Fix-Details werden als GitHub-Artefakte abgelegt und stehen für Audits zur Verfügung.

Entwickler:innen können den Fixer lokal als Dry-Run über `pre-commit run security-autofix --all-files` ausführen. Der CI-Lauf wendet Änderungen ausschließlich dann an, wenn alle Guards erfüllt sind; andernfalls bleibt die Entscheidung bei den Maintainer:innen.
