# Secret-Validierung

Die Secret-Validierung stellt sicher, dass hinterlegte Zugangsdaten für slskd und Spotify reproduzierbar geprüft werden können, ohne die Klartexte preiszugeben. Die Validierung kombiniert einen Format-Check mit einem Live-Ping auf die jeweilige Integration und degradiert deterministisch bei Netzwerkproblemen.

## Modi

| Modus  | Beschreibung                                                                 | Anwendungsfall                                      |
|--------|-------------------------------------------------------------------------------|-----------------------------------------------------|
| `live` | Live-Anfrage an den Upstream-Dienst. Timeout 800 ms (konfigurierbar).         | Upstream erreichbar → Ergebnis _gültig/ungültig_.   |
| `format` | Formatprüfung (Länge/Charset) auf dem Backend. Wird auch als Fallback genutzt. | Secret fehlt, ist fehlerhaft oder Upstream offline. |

Beim Fallback (`mode: format` mit `note: "upstream unreachable"`) bleibt der zuletzt geprüfte Status `unknown`. Das UI kennzeichnet diesen Zustand entsprechend.

## Endpunkt

`POST /api/v1/secrets/{provider}/validate`

```jsonc
// Anfrage (optional Override)
{ "value": "<override>" }

// Erfolg mit Live-Ping
{
  "ok": true,
  "data": {
    "provider": "slskd_api_key",
    "validated": {
      "mode": "live",
      "valid": true,
      "at": "2025-01-01T12:00:00Z"
    }
  },
  "error": null
}

// Fallback (Timeout)
{
  "ok": true,
  "data": {
    "provider": "spotify_client_secret",
    "validated": {
      "mode": "format",
      "valid": true,
      "note": "upstream unreachable",
      "at": "2025-01-01T12:00:00Z"
    }
  },
  "error": null
}
```

### Fehlerfälle

| Status | Code                | Ursache                                     |
|--------|---------------------|---------------------------------------------|
| 400    | `VALIDATION_ERROR`  | Override leer oder unbekannter Provider.    |
| 424    | `DEPENDENCY_ERROR`  | Upstream-Rate-Limit (`429`).                |
| 503    | `DEPENDENCY_ERROR`  | Upstream antwortet mit `5xx`.               |

## Provider-spezifische Checks

### slskd

- Request: `GET {SLSKD_URL}/api/v2/me` mit `X-API-Key`.
- Erfolgreich bei Status `2xx`.
- `401/403` → ungültige Credentials.
- `429` → `DEPENDENCY_ERROR` (`424`).
- `5xx` → `DEPENDENCY_ERROR` (`503`).
- Timeout/Netzfehler → `mode: format`, `note: upstream unreachable`.

### Spotify

- Request: `POST https://accounts.spotify.com/api/token` mit `grant_type=client_credentials` und Basic Auth (`client_id:client_secret`).
- Erfolgreich bei Status `200`.
- `400/401` → ungültige Credentials.
- `429` → `DEPENDENCY_ERROR` (`424`).
- `5xx` → `DEPENDENCY_ERROR` (`503`).
- Timeout/Netzfehler → `mode: format`, `note: upstream unreachable`.

## Konfiguration

| Variable                        | Default            | Beschreibung                              |
|---------------------------------|--------------------|-------------------------------------------|
| `SECRET_VALIDATE_TIMEOUT_MS`    | `800`              | Request-Timeout pro Ping (in Millisekunden). |
| `SECRET_VALIDATE_MAX_PER_MIN`   | `3`                | In-Memory-Rate-Limit pro Provider.        |
| `SLSKD_BASE_URL`                | `http://localhost:5030` | Fallback-URL, falls keine Setting-URL gesetzt ist. |

Alle Werte werden zur Laufzeit ausgewertet; das Rate-Limit gilt pro Instanz.

## Frontend

Das Settings-Panel stellt für beide Provider einen Button „Jetzt testen“ bereit. Das Ergebnis wird inline mit Modus, Status, Timestamp sowie optionaler Begründung/Hinweis dargestellt. Während des Requests ist der Button deaktiviert; Fehler (z. B. `DEPENDENCY_ERROR`) werden als Toast angezeigt.

