import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import DownloadsPage from '../pages/DownloadsPage';
import { renderWithProviders } from '../test-utils';
import { cancelDownload, fetchActiveDownloads, retryDownload, startDownload } from '../lib/api';

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  fetchActiveDownloads: jest.fn(),
  startDownload: jest.fn(),
  cancelDownload: jest.fn(),
  retryDownload: jest.fn()
}));

const mockedFetchDownloads = fetchActiveDownloads as jest.MockedFunction<typeof fetchActiveDownloads>;
const mockedStartDownload = startDownload as jest.MockedFunction<typeof startDownload>;
const mockedCancelDownload = cancelDownload as jest.MockedFunction<typeof cancelDownload>;
const mockedRetryDownload = retryDownload as jest.MockedFunction<typeof retryDownload>;

const toastMock = jest.fn();

describe('DownloadsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders downloads table', async () => {
    mockedFetchDownloads.mockResolvedValue([
      {
        id: 1,
        filename: 'Test File.mp3',
        status: 'running',
        progress: 45,
        created_at: '2024-01-01T12:00:00Z'
      }
    ]);

    renderWithProviders(<DownloadsPage />, { toastFn: toastMock, route: '/downloads' });

    expect(await screen.findByText('Test File.mp3')).toBeInTheDocument();
    expect(mockedFetchDownloads).toHaveBeenCalled();
    expect(mockedFetchDownloads.mock.calls[0][0]).toBeUndefined();
    expect(screen.getByText('45%')).toBeInTheDocument();
    const expectedDateLabel = new Intl.DateTimeFormat(undefined, {
      dateStyle: 'short',
      timeStyle: 'short'
    }).format(new Date('2024-01-01T12:00:00Z'));

    await waitFor(() => expect(screen.getByText(expectedDateLabel)).toBeInTheDocument());
  });

  it('starts a download via the form', async () => {
    mockedFetchDownloads.mockResolvedValue([]);
    mockedStartDownload.mockResolvedValue({
      id: 2,
      filename: 'Another File.mp3',
      status: 'queued',
      progress: 0,
      created_at: '2024-01-02T08:15:00Z'
    });

    renderWithProviders(<DownloadsPage />, { toastFn: toastMock, route: '/downloads' });

    await userEvent.type(screen.getByLabelText('Track-ID'), 'track-123');
    await userEvent.click(screen.getByRole('button', { name: 'Download starten' }));

    await waitFor(() => expect(mockedStartDownload).toHaveBeenCalledWith({ track_id: 'track-123' }));
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Download gestartet' })
    );
  });

  it('shows toast on download error', async () => {
    mockedFetchDownloads.mockResolvedValue([]);
    mockedStartDownload.mockRejectedValue(new Error('failed'));

    renderWithProviders(<DownloadsPage />, { toastFn: toastMock, route: '/downloads' });

    await userEvent.type(screen.getByLabelText('Track-ID'), 'track-404');
    await userEvent.click(screen.getByRole('button', { name: 'Download starten' }));

    await waitFor(() => expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ title: 'Download fehlgeschlagen' })));
  });

  it('toggles between active and all downloads', async () => {
    mockedFetchDownloads.mockResolvedValueOnce([
      {
        id: 3,
        filename: 'Running File.mp3',
        status: 'running',
        progress: 50,
        created_at: '2024-02-01T10:00:00Z'
      }
    ]);
    mockedFetchDownloads.mockResolvedValueOnce([
      {
        id: 3,
        filename: 'Running File.mp3',
        status: 'running',
        progress: 50,
        created_at: '2024-02-01T10:00:00Z'
      },
      {
        id: 4,
        filename: 'Completed File.mp3',
        status: 'completed',
        progress: 100,
        created_at: '2024-02-01T09:00:00Z'
      }
    ]);
    mockedFetchDownloads.mockResolvedValue([
      {
        id: 3,
        filename: 'Running File.mp3',
        status: 'running',
        progress: 50,
        created_at: '2024-02-01T10:00:00Z'
      },
      {
        id: 4,
        filename: 'Completed File.mp3',
        status: 'completed',
        progress: 100,
        created_at: '2024-02-01T09:00:00Z'
      }
    ]);

    renderWithProviders(<DownloadsPage />, { toastFn: toastMock, route: '/downloads' });

    expect(await screen.findByText('Running File.mp3')).toBeInTheDocument();
    expect(mockedFetchDownloads.mock.calls[0][0]).toBeUndefined();

    const toggleButton = screen.getByRole('button', { name: 'Alle anzeigen' });
    await userEvent.click(toggleButton);

    await waitFor(() =>
      expect(mockedFetchDownloads).toHaveBeenLastCalledWith({ includeAll: true })
    );
    expect(await screen.findByText('Completed File.mp3')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Nur aktive' })).toBeInTheDocument();
  });

  it('cancels a running download', async () => {
    mockedFetchDownloads.mockResolvedValueOnce([
      {
        id: 5,
        filename: 'Cancelable File.mp3',
        status: 'running',
        progress: 30,
        created_at: '2024-03-01T12:00:00Z'
      }
    ]);
    mockedFetchDownloads.mockResolvedValue([
      {
        id: 5,
        filename: 'Cancelable File.mp3',
        status: 'cancelled',
        progress: 30,
        created_at: '2024-03-01T12:00:00Z'
      }
    ]);
    mockedCancelDownload.mockResolvedValue();

    renderWithProviders(<DownloadsPage />, { toastFn: toastMock, route: '/downloads' });

    const cancelButton = await screen.findByRole('button', { name: 'Abbrechen' });
    await userEvent.click(cancelButton);

    await waitFor(() => expect(mockedCancelDownload).toHaveBeenCalledWith('5'));
    await waitFor(() => expect(mockedFetchDownloads).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText(/cancelled/i)).toBeInTheDocument());
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Download abgebrochen' })
    );
  });

  it('retries a failed download', async () => {
    mockedFetchDownloads.mockResolvedValueOnce([
      {
        id: 6,
        filename: 'Broken File.mp3',
        status: 'failed',
        progress: 0,
        created_at: '2024-03-02T09:00:00Z'
      }
    ]);
    mockedFetchDownloads.mockResolvedValue([
      {
        id: 6,
        filename: 'Broken File.mp3',
        status: 'failed',
        progress: 0,
        created_at: '2024-03-02T09:00:00Z'
      },
      {
        id: 7,
        filename: 'Broken File.mp3',
        status: 'queued',
        progress: 0,
        created_at: '2024-03-02T09:05:00Z'
      }
    ]);
    mockedRetryDownload.mockResolvedValue({
      id: 7,
      filename: 'Broken File.mp3',
      status: 'queued',
      progress: 0
    });

    renderWithProviders(<DownloadsPage />, { toastFn: toastMock, route: '/downloads' });

    const retryButton = await screen.findByRole('button', { name: 'Neu starten' });
    await userEvent.click(retryButton);

    await waitFor(() => expect(mockedRetryDownload).toHaveBeenCalledWith('6'));
    await waitFor(() => expect(mockedFetchDownloads).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getAllByText(/queued/i).length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getAllByText('Broken File.mp3').length).toBeGreaterThan(1));
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Download neu gestartet' })
    );
  });
});
