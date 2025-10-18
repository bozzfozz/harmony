# UI Security & Session Model

## Session Authentication
- The `/ui/login` form accepts an API key and validates it against the existing `SecurityConfig`.
- On success the server stores an opaque session record containing the API-key fingerprint, assigned UI role, issued timestamp, and last-activity metadata.
- The browser receives a single session cookie `ui_session=<opaque>` flagged as `HttpOnly; Secure; SameSite=Lax`.
- Session renewal happens transparently on activity; idle sessions expire according to the backend security policy.
- API calls required by the UI are executed server-side using the stored fingerprint. No API key or Authorization header is ever emitted to the browser.

## CSRF Protection
- Each rendered HTML page sets a non-HttpOnly cookie `csrftoken=<signed>` and embeds the token in `<meta name="csrf-token" content="...">`.
- Mutating HTMX requests (`POST`, `PATCH`, `DELETE`) must send the header `X-CSRF-Token`.
- A startup script reads the meta tag and configures the global HTMX header via `hx-headers`.
- Tokens are rotated on login and can be invalidated server-side when the session is revoked.

## Roles & Authorization
- Supported roles: `read_only`, `operator`, `admin`.
- Default role is sourced from `UI_ROLE_DEFAULT`; per-user overrides can be defined via `UI_ROLE_OVERRIDES`.
- Role resolution happens when a session is created and is stored alongside the session record.
- Route guards enforce the minimum role declared in `docs/ui/fe-htmx-plan.md`. Destructive actions (purge, requeue, stop) require `admin`.

## Feature Flags
- Feature toggles disable both navigation items and server routes when set to `false`.
- Flags are evaluated during request handling and template rendering to ensure hidden features cannot be invoked via direct URLs.

### Environment Variables
| Name | Type | Default | Wirkung |
|------|------|---------|---------|
| `UI_ROLE_DEFAULT` | `str` (`read_only\|operator\|admin`) | `operator` | Mindestrolle für neue Sessions ohne Override. |
| `UI_ROLE_OVERRIDES` | `str` (comma-separated `user:role`) | `""` | Erzwingt Rollen für konkrete Nutzer-IDs/API-Key-Fingerprints. |
| `UI_FEATURE_SPOTIFY` | `bool` | `true` | Aktiviert die Spotify-Oberfläche und zugehörige Navigation. |
| `UI_FEATURE_SOULSEEK` | `bool` | `true` | Schaltet Soulseek-Suche, Queue und Jobs frei. |
| `UI_FEATURE_DLQ` | `bool` | `true` | Aktiviert DLQ-spezifische Tabellen und Aktionen. |
| `UI_FEATURE_IMPORTS` | `bool` | `true` | Schaltet die FREE-Ingest-Tools innerhalb von `/ui/spotify` (Drag&Drop-Uploads & Verarbeitung) frei. |
| `UI_ALLOW_CDN` | `bool` | `false` | Erlaubt Einbindung definierter CDN-Ressourcen (siehe `docs/ui/csp.md`). |
| `UI_LIVE_UPDATES` | `str` (`polling\|SSE`) | `polling` | Umschaltung zwischen HTMX-Polling (Standard) und SSE-Stream. |

## Logging & Monitoring
- Login attempts log user identifier (hash/fingerprint) and result without exposing the API key.
- CSRF failures produce structured warnings with request metadata to support incident analysis.
- Session issuance and revocation expose counters for monitoring.

## Operational Checklist
1. Ensure TLS termination so that `Secure` cookies are honored end-to-end.
2. Set `UI_ROLE_DEFAULT` and `UI_ROLE_OVERRIDES` before enabling `/ui` in production.
3. Confirm that `UI_ALLOW_CDN` is left `false` unless the CSP has been updated with the documented SRI hashes.
4. Review feature-flag defaults during rollout to avoid exposing unfinished flows.
