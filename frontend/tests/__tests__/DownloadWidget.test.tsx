import { screen, userEvent, waitFor } from '../../src/testing/dom-testing';
import DownloadWidget from '../../src/components/DownloadWidget';
import { renderWithProviders } from '../../src/test-utils';
import type { DownloadEntry } from '../../src/lib/api';

const downloadsState: DownloadEntry[] = [];

const cloneState = () => downloadsState.map((entry) => ({ ...entry }));

const cancelDownloadMock = jest.fn(async (id: string) => {
  const entry = downloadsState.find((item) => String(item.id) === id);
  if (entry) {
    entry.status = 'cancelled';
  }
});

const retryDownloadMock = jest.fn(async (id: string) => {
  const original = downloadsState.find((item) => String(item.id) === id);
  const retryEntry: DownloadEntry = {
    id: `${id}-retry`,
    filename: original?.filename ? `${original.filename} (Retry)` : 'Retry.mp3',
    status: 'queued',
    progress: 0
  };
  downloadsState.push(retryEntry);
  return retryEntry;
});

const fetchDownloadsMock = jest.fn(async () => cloneState());

jest.mock('../../src/lib/api', () => ({
  fetchDownloads: (...args: unknown[]) => fetchDownloadsMock(...args),
  cancelDownload: (...args: unknown[]) => cancelDownloadMock(...(args as [string])),
  retryDownload: (...args: unknown[]) => retryDownloadMock(...(args as [string]))
}));

describe('DownloadWidget cancel and retry actions', () => {
  beforeEach(() => {
    downloadsState.splice(0, downloadsState.length);
    fetchDownloadsMock.mockClear();
    cancelDownloadMock.mockClear();
    retryDownloadMock.mockClear();
  });

  it('cancels an active download and updates the status', async () => {
    downloadsState.push({
      id: 5,
      filename: 'Widget Track.mp3',
      status: 'running',
      progress: 50
    });

    renderWithProviders(<DownloadWidget />);

    await screen.findByText('Widget Track.mp3');

    const cancelButton = await screen.findByRole('button', { name: 'Abbrechen' });
    await userEvent.click(cancelButton);

    expect(cancelDownloadMock).toHaveBeenCalledWith('5');

    await waitFor(() => {
      expect(screen.getByText('Cancelled')).toBeInTheDocument();
    });
    expect(fetchDownloadsMock).toHaveBeenCalledTimes(2);
  });

  it('retries a cancelled download and shows the retried entry', async () => {
    downloadsState.push({
      id: 9,
      filename: 'Cancelled Track.mp3',
      status: 'cancelled',
      progress: 0
    });

    renderWithProviders(<DownloadWidget />);

    await screen.findByText('Cancelled Track.mp3');

    const retryButton = await screen.findByRole('button', { name: 'Neu starten' });
    await userEvent.click(retryButton);

    expect(retryDownloadMock).toHaveBeenCalledWith('9');

    await waitFor(() => {
      expect(screen.getByText('9-retry')).toBeInTheDocument();
    });
    expect(fetchDownloadsMock).toHaveBeenCalledTimes(2);
  });
});
