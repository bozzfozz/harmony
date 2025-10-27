# Troubleshooting

Common operational issues and their remediation steps. Combine these with the
self-check CLI (`python -m app.ops.selfcheck --assert-startup`) and the health endpoints
(`/live`, `/api/health/ready`).

## Quick Reference

| Symptom | Likely Cause | Resolution |
| --- | --- | --- |
| Port 8080 already in use | Another service listens on the host port. | Stop the conflicting service or map Harmony to a different host port (`-p 8080:8080` → `-p 18080:8080`). Update exposed URLs and `ALLOWED_ORIGINS` accordingly. |
| `/api/health/ready` returns `503` with DB errors | SQLite file missing or unreadable. | Ensure the `/data` volume is writable. Remove stale locks or recreate the database with `DB_RESET=1` (last resort). |
| Downloads remain in "pending" | HDM cannot reach slskd or lacks credentials. | Verify `SLSKD_BASE_URL` and `SLSKD_API_KEY`. Use `curl` from the container to confirm connectivity. |
| OAuth flow fails with `OAUTH_STATE_MISMATCH` | Redirect URL changed or state expired. | Restart the flow from the UI or API; avoid opening multiple tabs. |
| Spotify callback shows `ERR_CONNECTION_REFUSED` | Browser cannot reach `127.0.0.1:8888`. | Replace the host with the actual server IP or tunnel the port (`ssh -N -L 8888:127.0.0.1:8888 ...`). |
| Music files missing after restart | Volumes not mounted persistently. | Mount `/downloads` and `/music` to host directories. Verify container logs for mount warnings. |
| `Unable to create downloads directory` in container logs | Host directory mapped to `/downloads` missing or lacking write permissions for the container user. | Run `python -m scripts.preflight_volume_check` (or recreate the directory) and ensure ownership matches `PUID`/`PGID` (`sudo chown 1000:1000 <path>` by default). Restart the container afterwards. |
| `OAUTH_SPLIT_MODE=true` fails at startup | Missing shared state directory or wrong permissions. | Mount the same host directory to `/config/runtime/oauth_state` for both API and callback services. Ensure ownership matches `PUID`/`PGID`. |
| Browser client fails with CORS errors | `ALLOWED_ORIGINS` not aligned with the browser URL. | Set the variable to the public URL (e.g. `http://localhost:8080`). |
| Ready probe stuck on `dependency: spotify` | Spotify API unreachable or credentials invalid. | Check connectivity, rotate Spotify secrets, rerun the OAuth flow. |
| Docker volume permission denied | Host paths owned by root. | Set `PUID`/`PGID` to match host user IDs or `chown` the directories to the container user. |

## Diagnostic Tips

- Inspect structured logs using `docker logs -f harmony | jq -R 'fromjson?'` to surface
  key/value fields.
- Use `python -m app.ops.selfcheck --assert-startup` before deployments to validate
  environment configuration and filesystem permissions.
- The smoke harness (`make smoke`) automatically executes the self-check. Control the
  behaviour via `SMOKE_SELFCHECK=off|warn|strict` (default: `warn`). In strict mode the
  harness aborts when startup guards fail.
- Inspect and replay DLQ entries via the `/api/v1/dlq` endpoints (see
  [DLQ management guide](operations/dlq.md)) if HDM jobs fail repeatedly.
- Capture the output of `/api/health/ready?verbose=1` and include it when escalating
  incidents.

For HDM-specific runbooks see [HDM runbook](operations/runbooks/hdm.md). For Spotify-specific
advice consult [`docs/auth/spotify.md`](auth/spotify.md).

## Startup Self-Check Reference

Run the guard locally via:

```bash
python -m app.ops.selfcheck --assert-startup
```

The command fails fast when directories or databases cannot be created. Structured log
lines such as `{"event": "sqlite.bootstrap.parent_not_writable", "parent": "/data"}`
indicate missing write permissions on the database directory. Resolve permission errors by
aligning host ownership (`chown <uid>:<gid> <path>`) with the container's `PUID`/`PGID`
or by mounting writable directories. Re-run the command until it returns exit code `0`
and confirms `"event": "sqlite.bootstrap.ready"` for the SQLite path. The smoke harness
emits the same events, making failures visible early in CI and local workflows.
