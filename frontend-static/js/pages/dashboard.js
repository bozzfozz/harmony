import { fetchJson, FetchError } from '../fetch-client.js';
import {
  getApiBase,
  qs,
  renderDefinitionList,
  setStatusBadge,
  setText,
  safeText,
  formatDateTime,
  formatRelative,
} from '../ui.js';

const apiBase = getApiBase();

const liveTile = document.getElementById('tile-live');
const healthTile = document.getElementById('tile-health');
const readyTile = document.getElementById('tile-ready');
const spotifyTile = document.getElementById('tile-spotify');
const downloadsTile = document.getElementById('tile-downloads');

function describeError(error) {
  if (error instanceof FetchError) {
    const { status, statusText } = error;
    if (status) {
      return `${status} ${statusText || ''}`.trim();
    }
    if (error.cause) {
      return error.cause.message || 'Network error';
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function updateLive(data) {
  const statusEl = qs(liveTile, '[data-field="status"]');
  const versionEl = qs(liveTile, '[data-field="version"]');
  const updatedEl = qs(liveTile, '[data-field="updated"]');
  const status = data?.status ?? 'unknown';
  setStatusBadge(statusEl, status);
  setText(versionEl, data?.version ? `Version ${data.version}` : 'Version unknown');
  setText(updatedEl, `Checked ${formatDateTime(new Date())}`);
}

function updateHealth(payload) {
  const statusEl = qs(healthTile, '[data-field="status"]');
  const list = qs(healthTile, '[data-field="details"]');
  const ok = payload?.ok ?? false;
  const data = payload?.data ?? {};
  setStatusBadge(statusEl, ok ? data.status ?? 'ok' : 'degraded');
  const uptimeSeconds = data?.uptime_s ?? null;
  const uptime = uptimeSeconds != null ? `${Math.round(uptimeSeconds / 60)} min` : '—';
  renderDefinitionList(list, [
    ['Status', data?.status ?? 'unknown'],
    ['Version', data?.version ?? 'unknown'],
    ['Uptime', uptime],
  ]);
}

function updateReadiness(payload) {
  const statusEl = qs(readyTile, '[data-field="status"]');
  const depsList = qs(readyTile, '[data-field="dependencies"]');
  if (!payload?.ok) {
    setStatusBadge(statusEl, 'degraded');
    renderDefinitionList(depsList, [['Error', payload?.error?.detail ?? 'Service not ready']]);
    return;
  }
  const data = payload.data ?? {};
  setStatusBadge(statusEl, 'ready');
  const dependencyEntries = Object.entries(data.deps || {});
  const orchestratorEntries = Object.entries(data.orchestrator?.components || {});
  const jobs = Object.entries(data.orchestrator?.jobs || {});
  const summary = [
    ['Database', data.db ?? 'unknown'],
    ['Dependencies healthy', `${dependencyEntries.filter(([, status]) => status === 'up').length}/${dependencyEntries.length}`],
    ['Scheduler', orchestratorEntries.find(([name]) => name === 'scheduler')?.[1] ?? 'unknown'],
    ['Dispatcher', orchestratorEntries.find(([name]) => name === 'dispatcher')?.[1] ?? 'unknown'],
  ];
  renderDefinitionList(depsList, summary.concat(jobs.map(([job, status]) => [`Job: ${job}`, status])));
}

function updateSpotify(payload) {
  const statusEl = qs(spotifyTile, '[data-field="status"]');
  const summaryEl = qs(spotifyTile, '[data-field="summary"]');
  const backend = payload?.store?.backend ?? 'unknown';
  const manual = payload?.manual_enabled ? 'Manual completion enabled' : 'Manual completion disabled';
  setStatusBadge(statusEl, `TTL ${payload?.ttl_seconds ?? 'unknown'}s`);
  setText(summaryEl, `${manual} · Backend: ${backend}`);
}

function updateDownloads(queued, active) {
  const summaryEl = qs(downloadsTile, '[data-field="summary"]');
  const nextEl = qs(downloadsTile, '[data-field="next"]');
  const queuedItems = queued?.downloads ?? [];
  const activeItems = active?.downloads ?? [];
  const totalQueued = queuedItems.length;
  const totalActive = activeItems.length;
  setText(summaryEl, `${totalQueued} queued · ${totalActive} active`);
  if (queuedItems.length > 0) {
    const first = queuedItems[0];
    const label = first.filename || `${first.artist ?? ''} – ${first.title ?? ''}`;
    const age = formatRelative(first.updated_at ?? first.created_at);
    setText(nextEl, `Next: ${safeText(label)} (${age})`);
  } else {
    setText(nextEl, 'Queue is empty');
  }
}

(async () => {
  const liveRequest = fetchJson('/live');
  const healthRequest = fetchJson(`${apiBase}/system/health`);
  const readyRequest = fetchJson(`${apiBase}/system/ready`);
  const spotifyRequest = fetchJson(`${apiBase}/oauth/health`);
  const queuedRequest = fetchJson(`${apiBase}/downloads?status=queued&limit=5`);
  const activeRequest = fetchJson(`${apiBase}/downloads?status=downloading&limit=5`);

  const [
    liveResult,
    healthResult,
    readyResult,
    spotifyResult,
    queuedResult,
    activeResult,
  ] = await Promise.allSettled([
    liveRequest.promise,
    healthRequest.promise,
    readyRequest.promise,
    spotifyRequest.promise,
    queuedRequest.promise,
    activeRequest.promise,
  ]);

  if (liveResult.status === 'fulfilled') {
    updateLive(liveResult.value);
  } else {
    setText(qs(liveTile, '[data-field="status"]'), 'error');
    setText(qs(liveTile, '[data-field="version"]'), describeError(liveResult.reason));
  }

  if (healthResult.status === 'fulfilled') {
    updateHealth(healthResult.value);
  } else {
    setText(qs(healthTile, '[data-field="status"]'), 'error');
    renderDefinitionList(qs(healthTile, '[data-field="details"]'), [['Error', describeError(healthResult.reason)]]);
  }

  if (readyResult.status === 'fulfilled') {
    updateReadiness(readyResult.value);
  } else {
    setText(qs(readyTile, '[data-field="status"]'), 'error');
    renderDefinitionList(qs(readyTile, '[data-field="dependencies"]'), [['Error', describeError(readyResult.reason)]]);
  }

  if (spotifyResult.status === 'fulfilled') {
    updateSpotify(spotifyResult.value);
  } else {
    setText(qs(spotifyTile, '[data-field="status"]'), 'error');
    setText(qs(spotifyTile, '[data-field="summary"]'), describeError(spotifyResult.reason));
  }

  if (queuedResult.status === 'fulfilled' && activeResult.status === 'fulfilled') {
    updateDownloads(queuedResult.value, activeResult.value);
  } else {
    setText(qs(downloadsTile, '[data-field="summary"]'), 'Queue unavailable');
    const message = queuedResult.status === 'rejected'
      ? describeError(queuedResult.reason)
      : describeError(activeResult.reason);
    setText(qs(downloadsTile, '[data-field="next"]'), message);
  }
})();
