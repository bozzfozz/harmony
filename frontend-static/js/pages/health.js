import { fetchJson, FetchError } from '../fetch-client.js';
import {
  getApiBase,
  qs,
  renderDefinitionList,
  renderTable,
  showAlert,
  formatDateTime,
} from '../ui.js';

const apiBase = getApiBase();

const livePanel = document.getElementById('live-panel');
const liveDetails = qs(livePanel, '[data-field="details"]');
const readyPanel = document.getElementById('ready-panel');
const readySummary = qs(readyPanel, '[data-field="summary"]');
const readyDeps = qs(readyPanel, '[data-field="deps"]');
const readyOrchestrator = qs(readyPanel, '[data-field="orchestrator"]');
const readyMessage = qs(readyPanel, '[data-field="message"]');
const healthPanel = document.getElementById('api-health');
const healthSummary = qs(healthPanel, '[data-field="summary"]');
const healthMessage = qs(healthPanel, '[data-field="message"]');

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

async function loadLive() {
  try {
    const response = await fetchJson('/live').promise;
    renderDefinitionList(liveDetails, [
      ['Status', response?.status ?? 'unknown'],
      ['Version', response?.version ?? 'unknown'],
      ['Checked at', formatDateTime(new Date())],
    ]);
  } catch (error) {
    renderDefinitionList(liveDetails, [['Error', describeError(error)]]);
  }
}

async function loadReady() {
  showAlert(readyMessage, '');
  try {
    const payload = await fetchJson(`${apiBase}/system/ready`).promise;
    if (!payload?.ok) {
      showAlert(readyMessage, payload?.error?.detail ?? 'Service not ready', 'error');
      renderDefinitionList(readySummary, [['Status', 'not ready']]);
      renderTable(readyDeps, [], [{ key: 'dependency' }]);
      renderTable(readyOrchestrator, [], [{ key: 'component' }]);
      return;
    }
    const data = payload.data ?? {};
    renderDefinitionList(readySummary, [
      ['Database', data.db ?? 'unknown'],
      ['Dependencies', Object.keys(data.deps || {}).length],
      ['Checked at', formatDateTime(new Date())],
    ]);
    renderTable(
      readyDeps,
      Object.entries(data.deps || {}).map(([name, status]) => ({ name, status })),
      [
        { key: 'name', render: (row) => row.name },
        { key: 'status' },
      ],
    );
    renderTable(
      readyOrchestrator,
      Object.entries(data.orchestrator?.components || {}).map(([name, status]) => ({ name, status })),
      [
        { key: 'name', render: (row) => row.name },
        { key: 'status' },
      ],
    );
  } catch (error) {
    showAlert(readyMessage, describeError(error), 'error');
  }
}

async function loadSystemHealth() {
  showAlert(healthMessage, '');
  try {
    const response = await fetchJson(`${apiBase}/system/health`).promise;
    const data = response?.data ?? {};
    renderDefinitionList(healthSummary, [
      ['Status', data.status ?? 'unknown'],
      ['Version', data.version ?? 'unknown'],
      ['Uptime (s)', data.uptime_s ?? 'unknown'],
    ]);
  } catch (error) {
    showAlert(healthMessage, describeError(error), 'error');
    renderDefinitionList(healthSummary, [['Error', describeError(error)]]);
  }
}

document.querySelector('[data-action="refresh-live"]').addEventListener('click', () => {
  loadLive().catch((error) => {
    renderDefinitionList(liveDetails, [['Error', describeError(error)]]);
  });
});

document.querySelector('[data-action="refresh-ready"]').addEventListener('click', () => {
  loadReady().catch((error) => {
    showAlert(readyMessage, describeError(error), 'error');
  });
});

Promise.all([loadLive(), loadReady(), loadSystemHealth()]).catch((error) => {
  showAlert(healthMessage, describeError(error), 'error');
});
