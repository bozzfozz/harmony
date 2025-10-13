# Lokale FOSS-Only-Policy

Diese Richtlinie beschreibt, wie wir im Harmony-Repository sicherstellen, dass ausschließlich frei nutzbare Open-Source-Abhängigkeiten
und -Werkzeuge eingesetzt werden. Der Fokus liegt auf lokalen Guard-Läufen – es existiert **keine CI-Integration**.

## Geltungsbereich

- **Code & Skripte** im gesamten Repository (Backend, Frontend, Ops).
- **Dependency-Quellen** (Package-Manager, Vendoring, Container-Bases).
- **SaaS-/SDK-Einsatz** innerhalb des Codes, in Dockerfiles und in Dokumentation.

## Lizenzregeln

### Erlaubte Lizenzen (Allow-List)

- MIT, BSD-2-Clause, BSD-3-Clause
- Apache-2.0, MPL-2.0, ISC, CC0-1.0, Unlicense, Python-2.0
- GPL-, LGPL- und AGPL-Familie (inkl. „-only“ und „-or-later“ Varianten)

### Blockierte Lizenzen (Block-List)

- SSPL-1.0, BUSL-1.1
- Elastic License 2.0, Redis Source Available, Confluent Community License
- Polyform-*, Server Side Public License Varianten, proprietäre oder kommerzielle EULAs
- Sonstige „source-available“-Modelle mit Nutzungsrestriktionen

**Hinweis:** Lizenzangaben wie „Proprietary“ oder „Commercial“ gelten als blockiert. Fehlende Angaben („UNKNOWN“) werden im Strict-
Modus behandelt wie Blocker, bis eine valide OSI/FSF-Lizenz nachgewiesen ist.

## Registries & Bezugsquellen

- **Zugelassen**: `https://pypi.org`, `https://registry.npmjs.org`, `https://crates.io`, Maven Central, NuGet, der öffentliche Go Proxy.
- **Verboten**: Private oder tokenbasierte Registries, Vendor-Mirrors, Git-/HTTP-Zugriffe auf firmeneigene Artefaktserver.
- **Docker-Basisbilder**: Nur offizielle Images der Projekte `debian`, `ubuntu`, `alpine`, `python`, `node`. Abweichungen müssen entfernt
  oder auf freie Alternativen umgestellt werden.

## SaaS- und SDK-Regeln

- Proprietäre SDKs/Agents dürfen nur verwendet werden, wenn ein dauerhaft frei nutzbares Tier existiert **und** die Integration standardmäßig
  deaktiviert ist.
- Andernfalls sind SDKs, Agents oder API-Schlüssel zu entfernen. Dokumentiere temporäre Deaktivierungen im `Wiring-Report` einer PR.

## Lokaler FOSS-Guard

Das Skript [`scripts/dev/foss_guard.sh`](../../scripts/dev/foss_guard.sh) prüft alle relevanten Stacks und erzeugt
`reports/foss_guard_summary.md`.

### Betriebsmodi

| Modus | Aufruf | Verhalten | Exit-Code |
| --- | --- | --- | --- |
| WARN | `make foss-scan` | Verstöße werden gemeldet, aber der Lauf endet erfolgreich. | `0` |
| STRICT | `make foss-enforce` | Blockierte oder unbekannte Lizenzen, Off-Registry-Quellen und SaaS-Funde lassen den Lauf abbrechen. | `12` |

`FOSS_STRICT=true` aktiviert den Strict-Modus auch bei direktem Aufruf des Skripts.

### Report-Inhalt

Der Markdown-Report enthält für jedes erkannte Ökosystem eine Tabelle mit:

- Paketname & Version
- Lizenz (wie im Manifest/Metadata gefunden)
- Bezugsquelle/Registry oder URL
- Manifest/Lock-Datei
- Bewertung (`allow`, `unknown`, `block`) inkl. Begründung

Unknown-Lizenzen weisen auf fehlende Metadaten oder ungeklärte Lizenztexte hin. Im Strict-Modus gelten sie als Blocker.

### Abdeckung je Ökosystem

- **Python**: `requirements*.txt`, optional `pyproject.toml`. Lizenzen werden per `importlib.metadata` (mit Fallback auf bekannte Paket-
  Mappings) ermittelt. Zusätzliche Index-Optionen (`--extra-index-url`, `--index-url`, `--find-links`) werden blockiert.
- **Node.js**: `package-lock.json` / `npm-shrinkwrap.json`. Registry-URLs werden auf `registry.npmjs.org` geprüft.
- **Docker**: Alle `Dockerfile*` werden auf erlaubte Basis-Images geprüft.
- **Go/Rust/Java/.NET**: Das Skript meldet gefundene Manifeste. Derzeit erfolgt nur eine Warnung (keine automatische Lizenzauflösung).
- **SaaS-Scan**: Grep nach bekannten proprietären SDKs (z. B. Sentry, Datadog, New Relic). Funde werden im Report gelistet und müssen auf freie
  Nutzung oder Deaktivierung geprüft werden.

## Arbeitsablauf

1. **Vor jedem Commit/PR**: `make foss-scan` ausführen, Report prüfen und Verstöße direkt beheben.
2. **Vor Merge/Freigabe**: `make foss-enforce`. Bei Exit-Code `12` ist der Merge zu stoppen, bis alle Blocker geklärt sind.
3. **Reports anhängen**: Ausschnitt aus `reports/foss_guard_summary.md` im PR-Body erwähnen (Wiring-Report).
4. **Ausnahmen**: Nur Maintainer dürfen schriftlich eine Ausnahme freigeben. Dokumentiere den Link zur Freigabe im PR-Text und markiere den
   Befund im Report als „approved-exception“.

## Bereinigung & Hardening

- Entferne `.npmrc`, Pip-/Poetry-Konfigurationen oder andere Dateien mit Tokens, `always-auth` oder privaten Index-URLs.
- Passe Dockerfiles an, damit ausschließlich offizielle Basis-Images verwendet werden.
- Entferne proprietäre SDKs oder stelle sicher, dass sie nur im freien Tier laufen und standardmäßig deaktiviert sind.

## Troubleshooting

- **Lizenz unbekannt**: Prüfe Projekt-Homepage/Repository, ergänze ggf. LICENSE-Datei oder tausche Abhängigkeit aus.
- **Off-Registry-Fund**: Wechsele auf eine der freigegebenen Registries oder vendorisiere die Abhängigkeit transparent mit Lizenz-Hinweis.
- **SaaS-Fund**: Bewerte, ob wirklich ein proprietäres SDK eingebunden ist. Entferne oder feature-gate es, wenn kein freier Tarif existiert.

## Ausnahmeprozess

1. Issue mit Begründung eröffnen und Maintainer taggen.
2. Lizenztext, Nutzungsbedingungen und geplante Laufzeit dokumentieren.
3. Maintainer entscheidet (`approved` oder `rejected`).
4. Bei Freigabe: Report-Eintrag mit Kommentar „approved-exception <Issue-Link>“ versehen. Strict-Modus darf erst wieder erfolgreich sein,
   wenn der Eintrag entfernt oder die Ausnahme dokumentiert ist.

## Pflege & Ownership

- Owner: `Platform/Compliance`
- Guard-Skript: `scripts/dev/foss_guard.sh`
- Dokumentation: Dieses Dokument (`docs/compliance/foss_policy.md`) + Hinweise in `AGENTS.md`, README und PR-Template.

Aktualisierungen erfolgen synchron: Änderungen am Guard müssen den Report-Aufbau und diese Dokumentation anpassen.
