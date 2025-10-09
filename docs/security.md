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

## Security scans

Der CI-Workflow [`ci.yml`](../.github/workflows/ci.yml) führt `pip-audit` gegen `requirements.txt` aus. Falsche Positive lassen sich wie gewohnt über `pip-audit`-Ignore-Regeln adressieren; dokumentiere Ausnahmen im PR.

Zusätzliche Security-Tasks oder Toolchain-Anpassungen werden im Repository über reguläre CODX-Issues und Policies in [`AGENTS.md`](../AGENTS.md) gesteuert.
