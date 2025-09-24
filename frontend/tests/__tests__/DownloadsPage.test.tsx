import { screen, userEvent, waitFor } from '../../src/testing/dom-testing';
import DownloadsPage from '../../src/pages/DownloadsPage';
import { renderWithProviders } from '../../src/test-utils';
import type { DownloadEntry } from '../../src/lib/api';

const downloadsState: DownloadEntry[] = [];

const cloneState = () => downloadsState.map((entry) => ({ ...entry }));

const startDownloadMock = jest.fn();

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

const fetchActiveDownloadsMock = jest.fn(async () => cloneState());

jest.mock('../../src/lib/api', () => ({
  fetchActiveDownloads: (...args: unknown[]) => fetchActiveDownloadsMock(...args),
  cancelDownload: (...args: unknown[]) => cancelDownloadMock(...(args as [string])),
  retryDownload: (...args: unknown[]) => retryDownloadMock(...(args as [string])),
  startDownload: (...args: unknown[]) => startDownloadMock(...args)
}));

describe('DownloadsPage cancel and retry actions', () => {
  beforeEach(() => {
    downloadsState.splice(0, downloadsState.length);
    fetchActiveDownloadsMock.mockClear();
    cancelDownloadMock.mockClear();
    retryDownloadMock.mockClear();
  });

  it('cancels a running download and refreshes the status', async () => {
    downloadsState.push({
      id: 1,
      filename: 'Running Track.mp3',
      status: 'running',
      progress: 25
    });

    renderWithProviders(<DownloadsPage />);

    await screen.findByText('Running Track.mp3');

    const cancelButton = await screen.findByRole('button', { name: 'Abbrechen' });
    await userEvent.click(cancelButton);

    expect(cancelDownloadMock).toHaveBeenCalledWith('1');

    await waitFor(() => {
      expect(screen.getByText('Cancelled')).toBeInTheDocument();
    });
    expect(fetchActiveDownloadsMock).toHaveBeenCalledTimes(2);
  });

  it('retries a failed download and shows the new job in the list', async () => {
    downloadsState.push({
      id: 10,
      filename: 'Failed Track.mp3',
      status: 'failed',
      progress: 0
    });

    renderWithProviders(<DownloadsPage />);

    await screen.findByText('Failed Track.mp3');

    const retryButton = await screen.findByRole('button', { name: 'Neu starten' });
    await userEvent.click(retryButton);

    expect(retryDownloadMock).toHaveBeenCalledWith('10');

    await waitFor(() => {
      expect(screen.getByText('10-retry')).toBeInTheDocument();
    });
    expect(fetchActiveDownloadsMock).toHaveBeenCalledTimes(2);
  });
});
