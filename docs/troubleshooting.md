# Troubleshooting

Common operational issues and their remediation steps. Combine these with the
self-check CLI (`python -m app.ops.selfcheck --assert-startup`) and the health endpoints
(`/live`, `/api/health/ready`).

## Quick Reference

| Symptom | Likely Cause | Resolution |
| --- | --- | --- |
| Port 8080 already in use | Another service listens on the host port. | Stop the conflicting service or map Harmony to a different host port (`-p 8080:8080` → `-p 18080:8080`). Update `PUBLIC_BACKEND_URL`/`ALLOWED_ORIGINS` accordingly. |
| `/api/health/ready` returns `503` with DB errors | SQLite file missing or unreadable. | Ensure the `/data` volume is writable. Remove stale locks or recreate the database with `DB_RESET=1` (last resort). |
| Downloads remain in "pending" | HDM cannot reach slskd or lacks credentials. | Verify `SLSKD_BASE_URL` and `SLSKD_API_KEY`. Use `curl` from the container to confirm connectivity. |
| OAuth flow fails with `OAUTH_STATE_MISMATCH` | Redirect URL changed or state expired. | Restart the flow from the UI or API; avoid opening multiple tabs. |
| Spotify callback shows `ERR_CONNECTION_REFUSED` | Browser cannot reach `127.0.0.1:8888`. | Replace the host with the actual server IP or tunnel the port (`ssh -N -L 8888:127.0.0.1:8888 ...`). |
| Music files missing after restart | Volumes not mounted persistently. | Mount `/data/downloads` and `/data/music` to host directories. Verify container logs for mount warnings. |
| `OAUTH_SPLIT_MODE=true` fails at startup | Missing shared state directory or wrong permissions. | Mount the same host directory to `/data/runtime/oauth_state` for both API and callback services. Ensure ownership matches `PUID`/`PGID`. |
| `curl /live` works but UI fails with CORS | `ALLOWED_ORIGINS`/`PUBLIC_BACKEND_URL` not aligned with the browser URL. | Set both variables to the public URL (e.g. `http://localhost:8080`). |
| Ready probe stuck on `dependency: spotify` | Spotify API unreachable or credentials invalid. | Check connectivity, rotate Spotify secrets, rerun the OAuth flow. |
| Docker volume permission denied | Host paths owned by root. | Set `PUID`/`PGID` to match host user IDs or `chown` the directories to the container user. |

## Diagnostic Tips

- Inspect structured logs using `docker logs -f harmony | jq -R 'fromjson?'` to surface
  key/value fields.
- Use `python -m app.ops.selfcheck --assert-startup` before deployments to validate
  environment configuration and filesystem permissions.
- Replay DLQ entries via scripts in `scripts/dlq/` if HDM jobs fail repeatedly.
- Capture the output of `/api/health/ready?verbose=1` and include it when escalating
  incidents.

For HDM-specific runbooks see [HDM runbook](operations/runbooks/hdm.md). For Spotify-specific
advice consult [`docs/auth/spotify.md`](auth/spotify.md).
