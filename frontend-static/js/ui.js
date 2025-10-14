const apiBaseAttr = document.documentElement.dataset.apiBase || document.body?.dataset.apiBase;
const fallbackBase = '/api/v1';

export function getApiBase() {
  if (typeof window !== 'undefined' && window.__HARMONY_API_BASE__) {
    return String(window.__HARMONY_API_BASE__).trim() || fallbackBase;
  }
  return (apiBaseAttr && apiBaseAttr.trim()) || fallbackBase;
}

export function qs(root, selector) {
  const base = root ?? document;
  const element = base.querySelector(selector);
  if (!element) {
    throw new Error(`Element not found for selector: ${selector}`);
  }
  return element;
}

export function safeText(value) {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value);
    }
  }
  return String(value);
}

export function formatDateTime(value) {
  if (!value) {
    return '—';
  }
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return safeText(value);
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(date);
}

export function formatRelative(value) {
  if (!value) {
    return '—';
  }
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return safeText(value);
  }
  const diffMs = date.getTime() - Date.now();
  const absMs = Math.abs(diffMs);
  const units = [
    ['day', 86_400_000],
    ['hour', 3_600_000],
    ['minute', 60_000],
    ['second', 1_000],
  ];
  for (const [unit, ms] of units) {
    if (absMs >= ms || unit === 'second') {
      const valueRounded = Math.round(diffMs / ms);
      return new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }).format(
        valueRounded,
        unit,
      );
    }
  }
  return 'now';
}

export function renderDefinitionList(container, entries) {
  if (!container) {
    return;
  }
  const fragment = document.createDocumentFragment();
  entries.forEach(([term, description]) => {
    const dt = document.createElement('dt');
    dt.textContent = term;
    const dd = document.createElement('dd');
    dd.textContent = safeText(description);
    fragment.append(dt, dd);
  });
  container.innerHTML = '';
  container.append(fragment);
}

export function renderKeyValueTable(tbody, rows) {
  if (!tbody) {
    return;
  }
  const fragment = document.createDocumentFragment();
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    const keyCell = document.createElement('td');
    keyCell.textContent = row.key;
    const valueCell = document.createElement('td');
    if (row.render) {
      valueCell.append(row.render(row));
    } else {
      valueCell.textContent = safeText(row.value);
    }
    tr.append(keyCell, valueCell);
    fragment.append(tr);
  });
  tbody.innerHTML = '';
  tbody.append(fragment);
}

export function renderTable(tbody, rows, columns) {
  if (!tbody) {
    return;
  }
  const fragment = document.createDocumentFragment();
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    columns.forEach((column) => {
      const cell = document.createElement('td');
      if (column.render) {
        const rendered = column.render(row);
        if (rendered instanceof Node) {
          cell.append(rendered);
        } else {
          cell.textContent = safeText(rendered);
        }
      } else {
        cell.textContent = safeText(row[column.key]);
      }
      tr.append(cell);
    });
    fragment.append(tr);
  });
  tbody.innerHTML = '';
  if (!rows.length) {
    const emptyRow = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = columns.length || 1;
    cell.textContent = 'No records found.';
    emptyRow.append(cell);
    tbody.append(emptyRow);
    return;
  }
  tbody.append(fragment);
}

export function toggleBusy(element, busy) {
  if (!element) {
    return;
  }
  element.setAttribute('aria-busy', busy ? 'true' : 'false');
}

export function showAlert(container, message, variant = 'info') {
  if (!container) {
    return;
  }
  container.textContent = message || '';
  if (variant) {
    container.dataset.variant = variant;
  } else {
    delete container.dataset.variant;
  }
  container.hidden = !message;
}

export function setText(target, text) {
  if (!target) {
    return;
  }
  target.textContent = text ?? '';
}

export function link(text, href) {
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.textContent = text;
  anchor.className = 'inline-link';
  return anchor;
}

export function button(label, { onClick, variant = 'secondary', type = 'button' } = {}) {
  const btn = document.createElement('button');
  btn.type = type;
  btn.className = `button button--${variant}`;
  btn.textContent = label;
  if (typeof onClick === 'function') {
    btn.addEventListener('click', onClick);
  }
  return btn;
}

export function setStatusBadge(element, status) {
  if (!element) {
    return;
  }
  const label = status ? status.toString() : 'unknown';
  element.textContent = label;
  const normalized = label.toLowerCase();
  element.dataset.status = normalized;
}

export function resetForm(form) {
  if (form?.reset) {
    form.reset();
  }
}
