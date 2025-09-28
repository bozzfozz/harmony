# Fehlerbehandlung und API-Fehlervertrag

Die öffentliche Harmony-API liefert Fehler konsistent im folgenden JSON-Format:

```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "meta": {
      "fields": [
        {"name": "playlist_links", "message": "Input should be a valid list"}
      ]
    }
  }
}
```

## Fehlertypen

| HTTP-Status                | `error.code`        | Beschreibung                                               |
| -------------------------- | ------------------- | ---------------------------------------------------------- |
| `400 Bad Request`          | `VALIDATION_ERROR`  | Eingaben sind ungültig. Bei Body-Validierungsfehlern enthält `meta.fields` Details pro Feld. |
| `404 Not Found`            | `NOT_FOUND`         | Ressource existiert nicht.                                |
| `429 Too Many Requests`    | `RATE_LIMITED`      | Rate-Limit erreicht. `meta.retry_after_ms` enthält Millisekunden bis zum nächsten Versuch. |
| `424`/`502`/`503`/`504`    | `DEPENDENCY_ERROR`  | Upstream- oder Feature-Abhängigkeit nicht verfügbar.       |
| `5xx`                      | `INTERNAL_ERROR`    | Unerwarteter Serverfehler oder Authentifizierungsfehler.   |

### Meta-Daten

* `meta.fields`: Liste von `{name, message}` für Validierungsfehler.
* `meta.retry_after_ms`: Millisekunden bis zum erneuten Versuch (Rate-Limit).
* `meta.feature`: Deaktiviertes Feature bei 503-Antworten.
* Weitere Felder können je nach Fehlertyp ergänzt werden.

## Debugging

Jede Fehlerantwort enthält den Header `X-Debug-Id` zur Log-Korrelation. Ist die Umgebungsvariable `ERRORS_DEBUG_DETAILS=true` gesetzt, wird die Debug-ID zusätzlich in `error.meta.debug_id` sowie ein kurzer Hinweis (`hint`) im Payload ergänzt.

## Feature-Flags

* `FEATURE_UNIFIED_ERROR_FORMAT` (Standard: `true`): steuert den globalen Fehler-Handler.
* `ERRORS_DEBUG_DETAILS` (Standard: `false`): aktiviert erweiterte Debug-Angaben im Payload.

## Beispiele

### 404 – Ressource nicht gefunden

```json
{
  "ok": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "Watchlist entry was not found"
  }
}
```

### 429 – Rate-Limit

```json
{
  "ok": false,
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many requests",
    "meta": {
      "retry_after_ms": 2500
    }
  }
}
```

### 503 – Feature deaktiviert

```json
{
  "ok": false,
  "error": {
    "code": "DEPENDENCY_ERROR",
    "message": "Artwork feature is disabled by configuration.",
    "meta": {
      "feature": "artwork"
    }
  }
}
```

Weitere Beispiele finden sich in `tests/data/error_examples.json`.
