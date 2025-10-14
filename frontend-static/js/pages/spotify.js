import { fetchJson, FetchError } from '../fetch-client.js';
import {
  getApiBase,
  qs,
  renderDefinitionList,
  showAlert,
  formatDateTime,
  formatRelative,
} from '../ui.js';

const apiBase = getApiBase();

const healthPanel = document.getElementById('oauth-health');
const startButton = document.getElementById('start-oauth');
const sessionNote = document.getElementById('oauth-session');
const sessionStateEl = qs(sessionNote, '[data-field="state"]');
const sessionExpiresEl = qs(sessionNote, '[data-field="expires"]');
const statusOutput = document.getElementById('status-output');
const manualForm = document.getElementById('manual-form');
const manualStatus = document.getElementById('manual-status');
const checkStatusButton = document.getElementById('check-status');

let currentState = null;

function describeError(error) {
  if (error instanceof FetchError) {
    const { status, statusText, data } = error;
    if (status) {
      return `${status} ${statusText || ''}`.trim();
    }
    if (data?.message) {
      return data.message;
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

async function loadHealth() {
  const details = qs(healthPanel, '[data-field="details"]');
  const message = qs(healthPanel, '[data-field="message"]');
  try {
    const response = await fetchJson(`${apiBase}/oauth/health`).promise;
    renderDefinitionList(details, [
      ['Provider', response?.provider ?? 'spotify'],
      ['Backend', response?.store?.backend ?? 'memory'],
      ['Active transactions', response?.active_transactions ?? 0],
      ['Session TTL', response?.ttl_seconds != null ? `${response.ttl_seconds}s` : 'unknown'],
      ['Manual completion', response?.manual_enabled ? 'Enabled' : 'Disabled'],
      ['Redirect URI', response?.redirect_uri ?? 'unset'],
    ]);
    showAlert(message, '');
  } catch (error) {
    renderDefinitionList(details, [['Error', describeError(error)]]);
    showAlert(message, 'Unable to load OAuth health.', 'error');
  }
}

async function startOAuth() {
  startButton.disabled = true;
  statusOutput.textContent = 'Opening authorisation window…';
  try {
    const data = await fetchJson(`${apiBase}/oauth/start`).promise;
    currentState = data.state;
    sessionStateEl.textContent = data.state;
    const expires = data.expires_at ? formatDateTime(data.expires_at) : 'unknown';
    sessionExpiresEl.textContent = `${expires} (${formatRelative(data.expires_at)})`;
    sessionNote.hidden = false;
    statusOutput.textContent = 'Authorisation window opened.';
    window.open(
      data.authorization_url,
      'harmonySpotifyAuth',
      'noopener,width=520,height=720',
    );
  } catch (error) {
    statusOutput.textContent = describeError(error);
  } finally {
    startButton.disabled = false;
  }
}

async function checkStatus() {
  if (!currentState) {
    statusOutput.textContent = 'Start an OAuth session to check status.';
    return;
  }
  checkStatusButton.disabled = true;
  statusOutput.textContent = 'Checking status…';
  try {
    const data = await fetchJson(`${apiBase}/oauth/status/${encodeURIComponent(currentState)}`).promise;
    statusOutput.textContent = `Status: ${data.status} · ` +
      (data.completed_at ? `Completed ${formatRelative(data.completed_at)}` : 'Pending');
    if (data.manual_completion_available && data.manual_completion_url) {
      const link = document.createElement('a');
      link.href = data.manual_completion_url;
      link.textContent = 'Manual completion link';
      link.className = 'inline-link';
      statusOutput.append(' · ', link);
    }
  } catch (error) {
    statusOutput.textContent = describeError(error);
  } finally {
    checkStatusButton.disabled = false;
  }
}

async function submitManual(event) {
  event.preventDefault();
  const formData = new FormData(manualForm);
  const redirectUrl = formData.get('redirect_url');
  if (!redirectUrl) {
    manualStatus.textContent = 'Redirect URL is required.';
    return;
  }
  manualStatus.textContent = 'Submitting…';
  try {
    const data = await fetchJson(`${apiBase}/oauth/manual`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ redirect_url: redirectUrl }),
    }).promise;
    manualStatus.textContent = data.ok
      ? `Manual completion succeeded at ${formatDateTime(data.completed_at)}`
      : data.message || 'Manual completion failed.';
    if (data.ok && data.state) {
      currentState = data.state;
      sessionStateEl.textContent = data.state;
    }
  } catch (error) {
    manualStatus.textContent = describeError(error);
  }
}

startButton.addEventListener('click', () => {
  startOAuth().catch((error) => {
    statusOutput.textContent = describeError(error);
  });
});

checkStatusButton.addEventListener('click', () => {
  checkStatus().catch((error) => {
    statusOutput.textContent = describeError(error);
  });
});

manualForm.addEventListener('submit', (event) => {
  submitManual(event).catch((error) => {
    manualStatus.textContent = describeError(error);
  });
});

loadHealth().catch((error) => {
  const message = qs(healthPanel, '[data-field="message"]');
  showAlert(message, describeError(error), 'error');
});
