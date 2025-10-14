import { fetchJson, FetchError } from '../fetch-client.js';
import {
  getApiBase,
  qs,
  renderKeyValueTable,
  renderTable,
  showAlert,
  formatDateTime,
  safeText,
} from '../ui.js';

const apiBase = getApiBase();

const settingsPanel = document.getElementById('settings-panel');
const settingsBody = document.getElementById('settings-body');
const updatedText = qs(settingsPanel, '[data-field="updated"]');
const settingsMessage = qs(settingsPanel, '[data-field="message"]');
const settingsForm = document.getElementById('settings-form');
const settingsStatus = document.getElementById('settings-status');
const historyBody = document.getElementById('history-body');

function describeError(error) {
  if (error instanceof FetchError) {
    const { status, statusText, data } = error;
    if (status) {
      return `${status} ${statusText || ''}`.trim();
    }
    if (data?.detail) {
      return data.detail;
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

async function loadSettings() {
  showAlert(settingsMessage, '');
  try {
    const response = await fetchJson(`${apiBase}/settings`).promise;
    const entries = Object.entries(response?.settings ?? {}).sort(([a], [b]) => a.localeCompare(b));
    renderKeyValueTable(
      settingsBody,
      entries.map(([key, value]) => ({ key, value })),
    );
    updatedText.textContent = formatDateTime(response?.updated_at);
  } catch (error) {
    showAlert(settingsMessage, describeError(error), 'error');
  }
}

async function loadHistory() {
  try {
    const response = await fetchJson(`${apiBase}/settings/history`).promise;
    renderTable(
      historyBody,
      response?.history ?? [],
      [
        {
          key: 'changed_at',
          render: (row) => formatDateTime(row.changed_at),
        },
        { key: 'key' },
        {
          key: 'old_value',
          render: (row) => safeText(row.old_value ?? ''),
        },
        {
          key: 'new_value',
          render: (row) => safeText(row.new_value ?? ''),
        },
      ],
    );
  } catch (error) {
    renderTable(historyBody, [], [{ key: 'key' }]);
    showAlert(settingsMessage, describeError(error), 'error');
  }
}

async function submitSetting(event) {
  event.preventDefault();
  const formData = new FormData(settingsForm);
  const key = formData.get('key');
  const value = formData.get('value');
  if (!key) {
    settingsStatus.textContent = 'Key is required.';
    return;
  }
  settingsStatus.textContent = 'Saving…';
  try {
    await fetchJson(`${apiBase}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, value }),
    }).promise;
    settingsStatus.textContent = 'Saved.';
    settingsForm.reset();
    await Promise.all([loadSettings(), loadHistory()]);
  } catch (error) {
    settingsStatus.textContent = describeError(error);
  }
}

settingsForm.addEventListener('submit', (event) => {
  submitSetting(event).catch((error) => {
    settingsStatus.textContent = describeError(error);
  });
});

Promise.all([loadSettings(), loadHistory()]).catch((error) => {
  showAlert(settingsMessage, describeError(error), 'error');
});
