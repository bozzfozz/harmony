# Docker health check run (local CI)

## Context
The validation followed the README instructions for building and running the Harmony Docker image:

1. `docker build -t harmony-local:rc .`
2. `docker run --rm -d --name harmony-test -p 18080:8080 -v "$PWD/tmp-data:/data" harmony-local:rc`
3. Health probes via `curl http://127.0.0.1:18080/live` and `curl http://127.0.0.1:18080/api/health/ready?verbose=1`
4. Container log inspection for errors after stopping the test instance.

## Outcome
- Step 1 failed because the `docker` CLI is unavailable in the current execution environment.
- As a result, steps 2–4 were skipped to avoid cascading failures.

## Evidence
```
bash: command not found: docker
```

## Follow-up actions
- Re-run the same sequence on a workstation with Docker Engine installed.
- After a successful build, repeat the health probes and capture the container logs to confirm a clean startup.
