# Harmony Web UI Design Guidelines

Diese Richtlinie definiert das server-gerenderte Designsystem der Harmony-Web-UI. Alle Seiten werden über Jinja2-Templates unter `app/ui/templates` aufgebaut, dynamische Aktualisierungen erfolgen mit HTMX. Die folgenden Abschnitte beschreiben Layoutkonventionen, gemeinsame Strings, Farb- und Typografie-Vorgaben sowie konkrete Markup-Muster, die auf die in `app/ui/static/css/app.css` ausgelieferten Styles abgestimmt sind.

## 0. Rendering-Architektur

### 0.1 Layout-Templates
- **`layouts/base.j2`** stellt den Rahmen mit `<header>`, Alert-Region, `<main>` und Skript-Einbindungen bereit. Jede Seite muss dieses Layout direkt oder indirekt erweitern und den `layout`-Kontext (Navigation, Alerts, Modals) befüllen.
- **Spezialisierte Layouts** (`layouts/dashboard.j2`, `layouts/two_column.j2`, `layouts/detail.j2`) kapseln wiederkehrende Seitenstrukturen. Erweitere sie, wenn du strukturelle Slots wie `dashboard_primary` oder `sidebar` benötigst, anstatt eigene Wrapper zu bauen.
- **Footer & Modal-Container** werden bereits im Basislayout gesetzt. Zusätzliche Modals gehören in die entsprechenden Block-Erweiterungen, damit `data-role="modal-container"` konsistent bleibt.

```jinja
{% extends "layouts/dashboard.j2" %}
{% import "partials/_strings.j2" as strings %}

{% block dashboard_primary %}
  <section class="page-section page-section--card">
    <h2 class="page-section__title">{{ strings.section_heading('dashboard') }}</h2>
    {% include "partials/dashboard_status.j2" %}
  </section>
{% endblock %}
```

### 0.2 Partials & Fragments
- Wiederkehrendes Markup lebt unter `app/ui/templates/partials`. Verwende vorhandene Makros (`partials/nav.j2`, `partials/alerts.j2`, `partials/status_badges.j2`, `partials/forms.j2`) statt duplizierter Strukturen.
- Asynchrone Fragmente setzen die Klasse `.async-fragment` bzw. `.async-fragment__placeholder` und deklarieren `hx-target`/`hx-swap`, sodass HTMX-Antworten konsistent injiziert werden.
- Für Out-of-band-Updates (z. B. Navigation oder Statusbereiche) geben die Partials bereits `hx-swap-oob="outerHTML"` vor. Baue darauf auf, statt eigene Attribute zu erfinden.

### 0.3 Shared Strings
- Gemeinsame Texte und Labels kommen aus `partials/_strings.j2`. Nutze die Makros (`strings.app_name()`, `strings.nav_label(...)`, `strings.form_label(...)`), damit Namen, Buttons und Statusmeldungen zentral gepflegt bleiben.
- Neue Copy-Varianten werden dort ergänzt. Vermeide Hardcodings im Template, außer es handelt sich um rein lokale Texte.

## 1. Farben
Die Styles aus `app/ui/static/css/app.css` definieren zentrale CSS-Custom-Properties:

| Kontext | Variable | Wert |
|---------|----------|------|
| Primärer Hintergrund | `--color-bg` | `#0f1115` |
| Sekundäre Fläche | `--color-surface` | `#181c24` |
| Alternative Fläche | `--color-surface-alt` | `#1f2531` |
| Rahmen | `--color-border` | `rgba(195, 255, 255, 0.1)` |
| Primärer Text | `--color-text` | `#f4f6fb` |
| Muted Text | `--color-muted` | `#a3acc8` |
| Akzent | `--color-accent` | `#4ea8de` |
| Erfolg | `--color-success` | `#4ade80` |
| Fehler | `--color-danger` | `#ff6b6b` |

Statusabhängige Komponenten nutzen vordefinierte Modifier-Klassen:
- Alerts: `.alert--success`, `.alert--error`, `.alert--warning`
- Badges: `.status-badge--success`, `.status-badge--danger`, `.status-badge--muted`
- Buttons übernehmen standardmäßig das Akzent-Gradienten-Theme; zusätzliche Varianten werden als neue CSS-Klassen ergänzt, nicht inline.

## 2. Typografie
- Grundschrift ist `"Inter", "Segoe UI", system-ui, -apple-system, sans-serif` (siehe `body`-Regel).
- Headlines im Header nutzen uppercase (`header h1`), Seitenabschnitte verwenden `.page-section__title` für gewichtete Titel.
- Fließtext setzt auf `line-height: 1.6`. Meta-Informationen und Hinweise nutzen `color: var(--color-muted)` (z. B. `.dashboard-action-state__timestamp`, `.table-fragment .empty-state`).
- Verwende semantische HTML-Elemente (`<h1>`–`<h3>`, `<p>`, `<dl>`). Die vorhandenen Klassen im Stylesheet übernehmen Gewichtung und Letterspacing, zusätzliche Font-Anpassungen sollen nur über CSS-Erweiterungen erfolgen.

## 3. Spacing & Layout
- `header` besitzt bereits Padding `1.75rem 2.25rem` und ein Blur-Gradient. Zusätzliche Inhalte (Formulare, Buttons) müssen sich in die Flex-Struktur (`align-items: center; gap: 1.5rem`) einfügen.
- `main` rendert Inhalte als Grid mit `gap: 2rem` und `max-width: 1040px`. Sammle thematisch verwandte Bereiche in `<section class="page-section">`.
- Kartenartige Bereiche verwenden `.page-section--card` für Radius, Border und Schatten. Keine zusätzlichen Wrapper nötig.
- Collections setzen spezialisierte Layoutklassen:
  - `.dashboard-actions` und `.dashboard-action-button` für Aktionsleisten.
  - `.dashboard-action-state` und Unterelemente (`__header`, `__metric-list`, …) für Statusblöcke.
  - `.table` plus `.pagination` für tabellarische Daten.
  - `.alerts` hält gestapelte Meldungen oberhalb des `main`-Bereichs.
- Mobilverhalten ist in `app.css` definiert (Media Query `max-width: 720px`). Halte Strukturen schlicht, damit die bestehenden Breakpoints greifen.

## 4. Komponenten & Muster

### 4.1 Primäre Navigation
Die Navigation wird über `partials/nav.j2` erzeugt und nutzt `.primary-nav__link` inklusive `.is-active`-Modifier. Aktualisierungen per HTMX laufen über `hx-swap-oob="outerHTML"`.

```jinja
{% import "partials/nav.j2" as nav %}
{% import "partials/_strings.j2" as strings %}

{{ nav.render_primary_nav(layout.navigation.primary) }}

{# In einer HTMX-Antwort kann die Navigation out-of-band aktualisiert werden: #}
{{ nav.render_primary_nav_oob(updated_navigation) }}

<form action="{{ url_for('ui.logout') }}"
      method="post"
      hx-post="{{ url_for('ui.logout') }}"
      hx-target="#ui-alert-region"
      hx-swap="outerHTML">
  <button type="submit">{{ strings.button_label('logout') }}</button>
</form>
```

### 4.2 Alerts & Inline-Feedback
Blende Meldungen über `partials/alerts.j2` ein. Jede Nachricht ist ein `<p role="alert" class="alert alert--{level}">` und greift damit automatisch die Farbgebung.

```jinja
<div id="ui-alert-region" data-role="alert-region">
  {{ alerts.render_alerts(layout.alerts) }}
</div>
```

### 4.3 Karten & Sektionen
Kombiniere `.page-section` mit `.page-section--card`, um konsistente Panels zu rendern. Zusätzliche Überschriften verwenden `.page-section__title`.

```jinja
<section class="page-section page-section--card">
  <h2 class="page-section__title">{{ strings.section_heading('operations') }}</h2>
  <div class="dashboard-actions">
    <button class="dashboard-action-button"
            hx-post="{{ url_for('ui.trigger_sync') }}"
            hx-target="#dashboard-action-state"
            hx-swap="outerHTML"
            aria-busy="{{ 'true' if sync.busy else 'false' }}">
      {{ strings.button_label('dashboard.action.sync') }}
    </button>
  </div>
  {% include "partials/dashboard_action_state.j2" with context %}
</section>
```

### 4.4 Formulare & HTMX
Formulare nutzen das Standard-Grid (`main form { display: grid; gap: 1rem; }`). Inputs besitzen Fokuszustände und adaptieren `var(--color-accent)`. Ergänze `hx-post`, `hx-target` und `hx-indicator`, um progressive Enhancement zu gewährleisten.

```jinja
<form id="watchlist-form"
      hx-post="{{ url_for('ui.watchlist_add') }}"
      hx-target="#watchlist-table"
      hx-swap="outerHTML"
      class="page-section page-section--card">
  <label for="watchlist-query">{{ strings.form_label('search.query') }}</label>
  <input id="watchlist-query" name="query" required autocomplete="off" />

  <label for="watchlist-limit">{{ strings.form_label('search.limit') }}</label>
  <input id="watchlist-limit" name="limit" type="number" min="1" max="100" value="25" />

  <button type="submit">{{ strings.button_label('search.submit') }}</button>
</form>
```

### 4.5 Asynchrone Fragmente
Nutze `.async-fragment` als Hülle für Bereiche, die via HTMX nachgeladen werden. `data-role` kennzeichnet die Funktion für Tests und Skripte.

```jinja
<section class="async-fragment"
         id="jobs-fragment"
         data-role="jobs-fragment"
         hx-get="{{ url_for('ui.jobs_fragment') }}"
         hx-trigger="load, every 60s"
         hx-target="#jobs-fragment"
         hx-swap="outerHTML">
  <p class="async-fragment__placeholder">{{ strings.loading_placeholder() }}</p>
</section>
```

### 4.6 Tabellen & Pagination
Tabellen verwenden `.table` und ergänzende Hilfsklassen (`.table-fragment`, `.table-external-link`, `.pagination`). Die Struktur setzt auf semantisches `<table>`-Markup mit `<caption>`, `<thead>`, `<tbody>`.

```jinja
<div class="table-fragment" id="downloads-table">
  <table class="table">
    <caption>{{ strings.section_heading('downloads') }}</caption>
    <thead>
      <tr>
        <th scope="col">{{ strings.table_header('downloads.filename') }}</th>
        <th scope="col">{{ strings.table_header('downloads.status') }}</th>
      </tr>
    </thead>
    <tbody>
      {% for item in downloads %}
        <tr>
          <td>{{ item.filename }}</td>
          <td>{{ status_badges.render_badge(item.badge) }}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
  <nav class="pagination" aria-label="{{ strings.pagination_label('downloads') }}">
    <button hx-get="{{ url_for('ui.downloads', page=pagination.prev) }}" hx-target="#downloads-table"{% if not pagination.prev %} disabled{% endif %}>{{ strings.pagination_prev() }}</button>
    <button hx-get="{{ url_for('ui.downloads', page=pagination.next) }}" hx-target="#downloads-table"{% if not pagination.next %} disabled{% endif %}>{{ strings.pagination_next() }}</button>
  </nav>
</div>
```

### 4.7 Status-Badges & Fortschrittsanzeigen
Verwende `partials/status_badges.j2`, um Statuschips zu rendern. Die Varianten `success`, `danger` und `muted` greifen auf die oben definierten Farbwerte zurück. Für laufende Aufgaben ergänzen HTMX-Antworten `aria-busy="true"` auf Buttons (z. B. `.dashboard-action-button[aria-busy="true"]`) – die CSS-Selektoren kümmern sich um visuelles Feedback.

## 5. Interaktionen & States
- **Hover & Focus:** Buttons, Links und interaktive Flächen besitzen standardisierte Übergänge (`transition: var(--transition)`). Ergänze keine eigenen Inline-Transitions.
- **Focus-Outline:** `outline: 2px solid var(--color-accent)` ist global gesetzt. Lasse die Standard-Outline aktiv.
- **Disabled & Busy:** Buttons mit `disabled` oder `aria-busy="true"` reduzieren Sichtbarkeit (`opacity: 0.55` bzw. `.dashboard-action-button[aria-busy="true"]`). Nutze diese Attribute statt eigener Klassen.
- **Loader:** Für Upload- oder Sync-Status wird `cursor: progress` via `[aria-busy="true"]` aktiviert. Animierte Spinner werden serverseitig als SVG eingebunden; verwende vorhandene Komponenten oder erweitere `app.css` gezielt.

Diese Richtlinien sind verbindlich. Neue Muster müssen an den bestehenden Layout- und Partials-Aufbau anknüpfen und ihre Styles in `app/ui/static/css/app.css` hinterlegen.
