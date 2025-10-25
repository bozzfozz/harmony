# Soulseek UI v1.1 Blueprint

Dieses Dokument definiert die verbindliche Planungsgrundlage für alle Harmony-Oberflächen ab Version 1.1. Die Soulseek-Mockups (`docs/designs/soulseek_ui_mock.html`) stellen den visuellen und strukturellen Referenzpunkt dar. Bestehende und künftige Seiten müssen die nachfolgenden Vorgaben erfüllen, damit die Oberfläche als konsistentes Operations-Dashboard wahrgenommen wird.

## 1. Ziele & Scope
- **Konsistenz:** Jede Seite übernimmt das Soulseek-Grundlayout (Hero-Suche, KPI-Metriken, modulare Cards) und die Farb-/Typografieparameter aus dem Mock.
- **Fokus auf Operator-Workflows:** Primäre Aktionen und Statusindikatoren befinden sich im sofort sichtbaren Bereich (Above-the-Fold).
- **Erweiterbarkeit:** Module lassen sich ohne Layoutbruch hinzufügen oder austauschen (Grid-basierte Karten, klar definierte Breakpoints).
- **Implementierungsbasis:** Vorgaben sind direkt auf die bestehenden Jinja-Templates (`app/ui/templates`) und Styles (`app/ui/static/css/app.css`) abbildbar.

## 2. Seitenaufbau (Template-Archetyp)
Alle Seiten folgen dieser dreiteiligen Struktur:

1. **Hero-Header**
   - Enthält Seitentitel (`<h1>`), ein Untertitel-Statement (max. 240 Zeichen) und die Suchleiste.
   - KPI-Metriken und Status-Pills werden rechts bzw. im Grid unterhalb der Suche angezeigt.
   - Buttons für Primäraktionen (z. B. "Sync starten", "Neue Regel") sitzen in einer kompakten Button-Leiste.
2. **Operations-Deck**
   - Grid mit 2–3 Spalten (Desktop) bzw. stacked (≤720 px).
   - Cards zeigen Module wie Transfers, Räume, Health-Signale, Automationen. Jedes Modul besteht aus Header, KPI-Stripe, Content-Zone.
   - Interaktive Controls (Tabs, Filter, Tabellen) nutzen bestehende Komponentenklassen (`.dashboard-action-button`, `.table`, `.pagination`).
3. **Insight-Footing**
   - Timeline-, Log- oder Audit-Module, optionale Zusatzpanels.
   - Für Pages ohne zusätzliche Insights kann der Bereich entfallen, muss aber per `page-section` reserviert bleiben, damit Erweiterungen ohne Template-Bruch möglich sind.

### Referenz-Markup
```jinja
{% extends "layouts/dashboard.j2" %}
{% import "partials/_strings.j2" as strings %}

{% block dashboard_header %}
  <header class="soulseek-header">
    <h1>{{ strings.page_title('soulseek.operations') }}</h1>
    <p>{{ strings.page_subtitle('soulseek.operations') }}</p>
    {% include "partials/soulseek_search.j2" %}
    {% include "partials/soulseek_hero_metrics.j2" %}
  </header>
{% endblock %}

{% block dashboard_primary %}
  <section class="soulseek-grid">
    {% include "partials/soulseek_transfers.j2" %}
    {% include "partials/soulseek_rooms.j2" %}
    {% include "partials/soulseek_health.j2" %}
    {% include "partials/soulseek_automations.j2" %}
  </section>
  <section class="soulseek-insights">
    {% include "partials/soulseek_activity.j2" %}
  </section>
{% endblock %}
```

> **Hinweis:** Klassennamen dienen als Alias für das bestehende Layout. Neue Seiten können ihre Module benennen (`spotify_…`, `backfill_…`), müssen aber die dargestellte Struktur übernehmen.

## 3. Komponentenrichtlinie
| Komponente | Beschreibung | Bindende Eigenschaften |
|------------|--------------|------------------------|
| **Hero-Suche** | Prominentes Formular mit Query-Feld, optionalen Filterchips, CTA-Button. | Breite ≥ 360 px, Fokuszustände mit `var(--accent)`, HTMX-Targets deklarieren (`hx-target="#ui-alert-region"`). |
| **Status-Pills** | Inline-Badges für Cluster- oder Pipeline-Zustände. | Abgerundete `999px`, Farbcodierung analog Soulseek-Mock (`accent`, `secondary`, `danger`, `warning`). |
| **KPI-Karte** | Kompakte Metriken in Cards. | Mindestens ein Primärwert + sekundäre Info (`<small>`), Layout `display: grid; gap: 6px`. |
| **Module-Card** | Primary Content Container. | `.page-section.page-section--card`, Header mit `<h2>` und optionalem Action-Menü. |
| **Table & Pagination** | Datenlisten. | `.table` + `.pagination`, Sticky-Header optional (`position: sticky; top: calc(header-height + gap)`). |
| **Activity Stream** | Chronologische Events. | `<ol>`/`<ul>` mit Zeitstempeln, Visual Indikatoren (Icons oder Badges). |

## 4. Responsive Verhalten
- **≥1200 px:** Drei-Spalten-Grid (`grid-template-columns: repeat(3, minmax(0, 1fr))`), Hero-Karten `grid-column: span 2`.
- **720–1199 px:** Zwei Spalten, sekundäre Module rücken unter Primärmodule. Suchleiste bleibt oberhalb.
- **<720 px:** Alles gestapelt, Padding reduziert (`clamp`). Buttons wandern in vertikale Stacks.
- Interaktive Elemente müssen `min-touch-size: 44px` erfüllen.

## 5. Daten & Zustände
- **HTMX-Fragmente:** Jeder Modul-Card ist ein `section.async-fragment` mit eindeutiger ID und `hx-get`-Polling, wo Live-Daten nötig sind (Transfers, Health, Automationen).
- **Loading & Error States:** Placeholder (`.async-fragment__placeholder`) und Fehlermeldungen (`.alert.alert--error`) erscheinen im Modul, nicht global.
- **Suchindex:** Soulseek-Suche greift auf einen vereinheitlichten Endpunkt (`/soulseek/search`). Andere Produkte müssen ihr Backend unter demselben Schema anbieten (`/product/search`). TODO: API-Schema verfeinern.
- **Security:** Alle Formulare validieren Eingaben serverseitig, Logs sanitizen Querystrings.

## 6. Accessibility & Internationalisierung
- Überschriftenhierarchie strikt einhalten (ein `<h1>` pro Seite, Module mit `<h2>`/`<h3>`).
- Buttons und Links benötigen `aria-label`, falls der Text nicht selbsterklärend ist.
- Status-Pills tragen `role="status"` oder `aria-live="polite"`, wenn dynamisch aktualisiert.
- Texte kommen aus `partials/_strings.j2`; neue Keys folgen dem Präfix `soulseek.*` bzw. Produkt-spezifische Prefixe.

## 7. Implementierungs-Checklist
1. Seite erweitert `layouts/dashboard.j2` und fügt Hero-Header plus Search ein.
2. Mindestens vier Module im Operations-Deck (Transfers/Queues, Räume/Collections, Health, Automation/Audit).
3. Alle Module als `async-fragment` mit Loading/Error-Zuständen.
4. Search + Primäraktionen triggern HTMX-Requests mit Ziel `#ui-alert-region` und modulare Targets.
5. Responsive Verhalten über bestehende `app.css`-Breakpoints validiert (`npm run dev` optional für Storybook-PoC).
6. QA liefert Screenshots (Desktop & Mobile) vor Merge.
7. Tests: Mindestens 1 Template-Render-Test (Happy) + 1 Fehlerpfad (z. B. leere Datenliste).

## 8. Rollout-Plan Version 1.1
- **Phase 1 (Spotify, Soulseek):** Refactor bestehender Pages auf Archetyp, Reuse Hero-Module.
- **Phase 2 (Workers, Downloads, Integrationen):** Übernahme des Grids, Migration der Tabellen auf modulare Cards.
- **Phase 3 (Neue Seiten):** Blueprint als Default, Abweichungen bedürfen Design-Review.
- **Observability:** Instrumentiere jede Primäraktion mit strukturierten Logs (`action`, `resource`, `status`).
- **Rollback:** Alte Layouts bleiben bis Ende Phase 2 im Git, Branch-basierte Feature-Flags zur Sicherheit.

## 9. Alternativen & Entscheidung
- **Option A:** Eigenständige Layouts pro Produkt (Spotify, Soulseek, Downloads). *Vorteil:* Flexibilität für Spezialfälle. *Nachteil:* Höhere Pflegekosten, inkonsistente UX, schwieriger Rollout.
- **Option B (gewählt):** Einheitliches Soulseek-Archetyp-Layout als Blaupause. *Vorteil:* Hohe Wiedererkennung, zentrale Pflege von Komponenten, beschleunigter Implementierungsstart. *Risiko:* Spezialanforderungen benötigen Erweiterungspunkte → mit modularem Grid und optionalem Insight-Footing mitigiert.

## 10. Anhang
- **Figma/Mock:** `docs/designs/soulseek_ui_mock.html`
- **Stylesheet-Referenz:** `app/ui/static/css/app.css`
- **Template-Referenz:** `app/ui/templates/pages/` + `app/ui/templates/partials/`
- **Tracking:** Version 1.1 Roadmap-Eintrag im Projekt-Board `UI Refresh`.
