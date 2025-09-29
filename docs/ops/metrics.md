# Metrics & Prometheus Quickstart

Dieser Leitfaden beschreibt, wie du den Prometheus-Endpunkt von Harmony aktivierst, absicherst und in eine Prometheus-Instanz einbindest. Ergänzende Hintergrundinformationen findest du im Abschnitt „Health-, Readiness- und Metrics-Endpunkte“ des [README](../../README.md#health--readiness--und-metrics-endpunkte).

## Aktivierung

1. Setze in `.env`:
   ```bash
   FEATURE_METRICS_ENABLED=true
   METRICS_PATH=/metrics            # optional anpassbar
   METRICS_REQUIRE_API_KEY=true     # empfohlen in Produktion
   ```
2. Starte das Backend neu und überprüfe `/api/v1/ready`.
3. Rufe `<BASE_URL><METRICS_PATH>` im Browser oder per `curl` auf. Bei aktiviertem API-Key musst du `X-API-Key` bzw. `Authorization: Bearer` mitsenden.

## Authentifizierung

- Standard: `METRICS_REQUIRE_API_KEY=true` → Prometheus muss den API-Key mitsenden.
- Bei `false` fügt Harmony den Metrics-Pfad automatisch zur Allowlist hinzu. Schütze den Endpoint dann per Netzwerksegmentierung oder Reverse-Proxy.
- Mehrere Keys können via `HARMONY_API_KEYS` oder `HARMONY_API_KEYS_FILE` verwaltet werden – Prometheus sollte einen dedizierten Key erhalten.

## Beispiel-Prometheus-Konfiguration

```yaml
scrape_configs:
  - job_name: 'harmony'
    metrics_path: /metrics
    scheme: http
    static_configs:
      - targets: ['harmony-api:8000']
    authorization:
      credentials: '${HARMONY_METRICS_KEY}'  # über Prometheus-Secrets injizieren
```

Für `X-API-Key`-Authentifizierung ohne Bearer-Header kannst du alternativ `headers` verwenden:

```yaml
    headers:
      X-API-Key: '${HARMONY_METRICS_KEY}'
```

## Exponierte Standardmetriken

- `app_build_info` – Gauge mit der Backend-Version.
- `app_requests_total{method, path, status}` – Counter aller HTTP-Requests.
- `app_request_duration_seconds_bucket` + `_sum`/`_count` – Histogramm zur Request-Dauer.
- Zusätzlich registrieren Router & Services eigene Counter/Gauges über `MetricsRegistry.register_*`.

Die Buckets werden in `app/main.py` definiert (`_METRIC_BUCKETS`) und decken typische API-Latenzen ab.

## Fehlerbehebung

- 404 auf `/metrics` → `FEATURE_METRICS_ENABLED` ist `false` oder der Pfad unterscheidet sich (`METRICS_PATH`).
- 401/403 → API-Key fehlt oder ist falsch. Prüfe `HARMONY_API_KEYS`/`HARMONY_API_KEYS_FILE`.
- Keine neuen Samples → Request-Middleware wurde eventuell durch `METRICS_REQUIRE_API_KEY=false` entkoppelt und Prometheus erreicht den Endpoint ohne Authentifizierung, aber es erfolgen keine normalen Requests (nur Health-Checks). Prüfe mit `curl`, ob HTTP-Traffic wirklich fließt.

Weitere Details zur Health- und Readiness-API inklusive Beispielantworten findest du in [`docs/observability.md`](../observability.md).
