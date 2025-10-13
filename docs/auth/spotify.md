# Spotify OAuth Guide

Harmony supports two operating modes:

- **FREE** – Parser-based ingest without Spotify credentials.
- **PRO** – Full Spotify API integration via OAuth. This mode unlocks automatic
  backfill, playlist expansion and HDM-managed secrets.

The following steps configure and operate the PRO mode.

## Prerequisites

1. Create a Spotify application in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/).
2. Register the redirect URI `http://127.0.0.1:8888/callback` for local flows. You can
   add additional URIs for remote environments.
3. Obtain the Client ID and Client Secret and inject them via environment variables or
   the settings API/UI.

## OAuth Flow

1. **Start authorization** – Trigger `POST /api/v1/spotify/pro/oauth/start` or use the
   "Spotify PRO verbinden" button in the web UI. Harmony creates an OAuth transaction
   and redirects the browser to Spotify.
2. **Grant access** – After the user approves the scopes, Spotify redirects back to the
   configured callback URL with `code` and `state` parameters.
3. **Callback handling** – The bundled callback helper listens on
   `http://127.0.0.1:8888/callback`. Harmony exchanges the authorization code, stores the
   refresh token via the secret store and marks the transaction as complete.
4. **Verification** – `GET /spotify/status` must return `authorized: true`. HDM workers
   automatically resume PRO-only tasks.

All steps are idempotent; failed exchanges do not persist credentials.

## Callback on Remote Hosts

Spotify defaults to redirecting the browser to `127.0.0.1`. When Harmony runs on a
remote machine you can complete the flow in two ways:

- **Manual host swap:** Replace `127.0.0.1` in the redirected URL with the reachable host
  or IP before hitting enter. Example: change
  `http://127.0.0.1:8888/callback?code=XYZ&state=ABC` to
  `http://192.168.1.5:8888/callback?code=XYZ&state=ABC`.
- **Port forward:** Use SSH tunnelling to forward the callback port locally:

  ```bash
  ssh -N -L 8888:127.0.0.1:8888 user@remote-host
  ```

- **Manual completion:** POST the full redirect URL to
  `/api/v1/oauth/manual` when the browser cannot reach the callback service:

  ```bash
  curl -X POST \
    -H "Content-Type: application/json" \
    -H "X-API-Key: <your API key>" \
    -d '{"redirect_url": "http://127.0.0.1:8888/callback?code=XYZ&state=ABC"}' \
    http://localhost:8080/api/v1/oauth/manual
  ```

## Environment Variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `SPOTIFY_CLIENT_ID` | OAuth client ID from Spotify. | _(none)_ |
| `SPOTIFY_CLIENT_SECRET` | OAuth client secret. | _(none)_ |
| `SPOTIFY_REDIRECT_URI` | Overrides the callback URL presented to Spotify. | `http://127.0.0.1:8888/callback` |
| `OAUTH_CALLBACK_PORT` | Port used by the bundled callback app. | `8888` |
| `OAUTH_MANUAL_CALLBACK_ENABLE` | Enable manual completion endpoint. | `true` |
| `OAUTH_SESSION_TTL_MIN` | OAuth transaction lifetime in minutes. | `10` |
| `OAUTH_SPLIT_MODE` | Use a shared filesystem store when callback and API run separately. | `false` |
| `OAUTH_STATE_DIR` | Shared directory for state files. | `/data/runtime/oauth_state` |
| `OAUTH_STATE_TTL_SEC` | TTL of persisted state files. | `600` |
| `OAUTH_STORE_HASH_CV` | Hash PKCE code verifiers before storing them (set `false` in split mode). | `true` |
| `OAUTH_PUBLIC_HOST_HINT` | Optional hint displayed to the user (e.g. public hostname). | _(none)_ |
| `OAUTH_PUBLIC_BASE` | Public base path serving OAuth routes. | `/api/v1/oauth` |

## Troubleshooting

| Symptom | Cause | Resolution |
| --- | --- | --- |
| Callback opens `ERR_CONNECTION_REFUSED` | Port 8888 not reachable from the browser. | Use SSH port forwarding or replace `127.0.0.1` with the server IP in the callback URL. |
| `OAUTH_STATE_MISMATCH` in logs | The `state` parameter was modified or expired. | Restart the authorization flow; ensure only one browser tab is active. |
| `OAUTH_TOKEN_EXCHANGE_FAILED` | Spotify rejected the code (often due to redirect mismatch or reused code). | Verify that the redirect URI matches the Spotify app configuration and repeat the flow. |
| `/spotify/status` stays `authorized: false` | Secrets not stored or expired. | Rotate `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` and rerun the flow. |

Refer to [`docs/troubleshooting.md`](../troubleshooting.md) for additional operational
issues and recovery steps.
