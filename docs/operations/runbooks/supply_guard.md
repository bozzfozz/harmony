# Supply Guard Runbook

## Zweck

`scripts/dev/supply_guard.sh` stellt sicher, dass keine Build-Artefakte oder unerwünschten Dateien (z. B. `package-lock.json`, `node_modules/`, generierte Bundles) im Repository landen. Der Guard MUSS grün sein, bevor Änderungen eingecheckt werden.

## Ausführung

```bash
bash scripts/dev/supply_guard.sh
```

Der Lauf beendet sich mit Exit-Code `0`, wenn keine verbotenen Artefakte gefunden wurden. Bei einem Fund listet das Skript alle problematischen Pfade auf; diese Dateien sind zu löschen oder in `.gitignore` aufzunehmen.

## Letzter dokumentierter Lauf

- Datum: 2025-02-15 (UTC)
- Ergebnis: ✅ Keine Node-Build-Artefakte erkannt, `All checks passed.`
- Log-Auszug:
  ```
  [supply-guard][INFO] No Node build artifacts detected.
  [supply-guard] All checks passed.
  ```

Bei Änderungen an den Regeln oder neuen Build-Pipelines ist diese Runbook-Datei zu aktualisieren.
