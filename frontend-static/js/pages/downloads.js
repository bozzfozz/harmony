import { fetchJson, FetchError } from '../fetch-client.js';
import {
  getApiBase,
  qs,
  renderDefinitionList,
  renderTable,
  toggleBusy,
  showAlert,
  button,
  formatDateTime,
  formatRelative,
  safeText,
} from '../ui.js';

const apiBase = getApiBase();

const summaryPanel = document.getElementById('queue-summary');
const metricsList = qs(summaryPanel, '[data-field="metrics"]');
const summaryMessage = qs(summaryPanel, '[data-field="message"]');
const refreshButton = document.getElementById('refresh-queue');
const queuedTableBody = document.getElementById('queued-body');
const tableRegion = qs(document.getElementById('queued-downloads'), '.table-container');
const batchForm = document.getElementById('batch-form');
const batchStatus = document.getElementById('batch-status');

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

async function loadQueue() {
  toggleBusy(tableRegion, true);
  showAlert(summaryMessage, '');
  try {
    const [queued, active] = await Promise.all([
      fetchJson(`${apiBase}/downloads?status=queued&limit=25`).promise,
      fetchJson(`${apiBase}/downloads?status=downloading&limit=25`).promise,
    ]);
    const queuedItems = queued?.downloads ?? [];
    const activeItems = active?.downloads ?? [];
    renderDefinitionList(metricsList, [
      ['Queued items', queuedItems.length],
      ['Active downloads', activeItems.length],
      ['Last updated', formatDateTime(new Date())],
    ]);
    renderTable(
      queuedTableBody,
      queuedItems,
      [
        { key: 'id' },
        {
          key: 'filename',
          render: (row) => safeText(row.filename || `${row.artist ?? ''} – ${row.title ?? ''}`),
        },
        { key: 'priority' },
        {
          key: 'updated_at',
          render: (row) => formatRelative(row.updated_at ?? row.created_at),
        },
        { key: 'state' },
        {
          key: 'actions',
          render: (row) => {
            const group = document.createElement('div');
            group.className = 'form-actions';
            const cancelButton = button('Cancel', {
              variant: 'secondary',
              onClick: async () => {
                cancelButton.disabled = true;
                try {
                  await fetchJson(`${apiBase}/download/${row.id}`, {
                    method: 'DELETE',
                  }).promise;
                  await loadQueue();
                } catch (error) {
                  showAlert(summaryMessage, describeError(error), 'error');
                } finally {
                  cancelButton.disabled = false;
                }
              },
            });
            group.append(cancelButton);
            return group;
          },
        },
      ],
    );
  } catch (error) {
    showAlert(summaryMessage, describeError(error), 'error');
    renderTable(queuedTableBody, [], [
      { key: 'id' },
    ]);
  } finally {
    toggleBusy(tableRegion, false);
  }
}

async function submitBatch(event) {
  event.preventDefault();
  const formData = new FormData(batchForm);
  const requestedBy = formData.get('requested_by');
  const artist = formData.get('artist');
  const title = formData.get('title');
  if (!requestedBy || !artist || !title) {
    batchStatus.textContent = 'Please provide requested by, artist, and title.';
    return;
  }
  const payload = {
    requested_by: requestedBy,
    items: [
      {
        artist,
        title,
        album: formData.get('album') || null,
        isrc: formData.get('isrc') || null,
        priority: formData.get('priority') ? Number(formData.get('priority')) : null,
        requested_by: requestedBy,
      },
    ],
  };
  batchStatus.textContent = 'Submitting batch…';
  try {
    const response = await fetchJson(`${apiBase}/downloads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).promise;
    batchStatus.textContent = `Submitted batch ${response.batch_id} (${response.items_total} items).`;
    batchForm.reset();
    await loadQueue();
  } catch (error) {
    batchStatus.textContent = describeError(error);
  }
}

refreshButton.addEventListener('click', () => {
  loadQueue().catch((error) => {
    showAlert(summaryMessage, describeError(error), 'error');
  });
});

batchForm.addEventListener('submit', (event) => {
  submitBatch(event).catch((error) => {
    batchStatus.textContent = describeError(error);
  });
});

loadQueue().catch((error) => {
  showAlert(summaryMessage, describeError(error), 'error');
});
