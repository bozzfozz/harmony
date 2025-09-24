import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import DownloadWidget from '../components/DownloadWidget';
import { renderWithProviders } from '../test-utils';
import { cancelDownload, fetchDownloads, retryDownload } from '../lib/api';

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  fetchDownloads: jest.fn(),
  cancelDownload: jest.fn(),
  retryDownload: jest.fn()
}));

const mockedFetchDownloads = fetchDownloads as jest.MockedFunction<typeof fetchDownloads>;
const mockedCancelDownload = cancelDownload as jest.MockedFunction<typeof cancelDownload>;
const mockedRetryDownload = retryDownload as jest.MockedFunction<typeof retryDownload>;

const toastMock = jest.fn();

describe('DownloadWidget', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders active downloads', async () => {
    mockedFetchDownloads.mockResolvedValue([
      {
        id: 1,
        filename: 'Track One.mp3',
        status: 'running',
        progress: 45,
        priority: 2
      },
      {
        id: 2,
        filename: 'Track Two.mp3',
        status: 'queued',
        progress: 10,
        priority: 1
      }
    ]);

    renderWithProviders(<DownloadWidget />, { toastFn: toastMock, route: '/dashboard' });

    expect(await screen.findByText('Track One.mp3')).toBeInTheDocument();
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('45%')).toBeInTheDocument();
    expect(screen.getAllByText(/Priorität/)[0]).toHaveTextContent('Priorität: 2');
    expect(mockedFetchDownloads).toHaveBeenCalledWith({ limit: 5 });
  });

  it('shows empty state when no downloads are active', async () => {
    mockedFetchDownloads.mockResolvedValue([]);

    renderWithProviders(<DownloadWidget />, { toastFn: toastMock, route: '/dashboard' });

    expect(await screen.findByText('Keine aktiven Downloads.')).toBeInTheDocument();
  });

  it('shows toast when the API call fails', async () => {
    mockedFetchDownloads.mockRejectedValue(new Error('network error'));

    renderWithProviders(<DownloadWidget />, { toastFn: toastMock, route: '/dashboard' });

    await waitFor(() => expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Downloads konnten nicht geladen werden' })
    ));
    expect(screen.getByText('Downloads konnten nicht geladen werden.')).toBeInTheDocument();
  });

  it('navigates to downloads page when clicking show all', async () => {
    mockedFetchDownloads.mockResolvedValue([
      { id: 1, filename: 'A.mp3', status: 'running', progress: 60, priority: 5 },
      { id: 2, filename: 'B.mp3', status: 'running', progress: 40, priority: 4 },
      { id: 3, filename: 'C.mp3', status: 'running', progress: 20, priority: 3 },
      { id: 4, filename: 'D.mp3', status: 'running', progress: 10, priority: 2 },
      { id: 5, filename: 'E.mp3', status: 'running', progress: 5, priority: 1 },
      { id: 6, filename: 'F.mp3', status: 'running', progress: 2, priority: 1 }
    ]);

    renderWithProviders(<DownloadWidget />, { toastFn: toastMock, route: '/dashboard' });

    expect(await screen.findByText('A.mp3')).toBeInTheDocument();
    expect(screen.queryByText('F.mp3')).not.toBeInTheDocument();

    const button = await screen.findByRole('button', { name: 'Alle anzeigen' });
    await userEvent.click(button);

    await waitFor(() => expect(window.location.pathname).toBe('/downloads'));
  });

  it('hides the show all button when five or fewer downloads are available', async () => {
    mockedFetchDownloads.mockResolvedValue([
      { id: 1, filename: 'A.mp3', status: 'running', progress: 60, priority: 5 },
      { id: 2, filename: 'B.mp3', status: 'running', progress: 40, priority: 4 },
      { id: 3, filename: 'C.mp3', status: 'running', progress: 20, priority: 3 },
      { id: 4, filename: 'D.mp3', status: 'running', progress: 10, priority: 2 },
      { id: 5, filename: 'E.mp3', status: 'running', progress: 5, priority: 1 }
    ]);

    renderWithProviders(<DownloadWidget />, { toastFn: toastMock, route: '/dashboard' });

    expect(await screen.findByText('A.mp3')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Alle anzeigen' })).not.toBeInTheDocument());
  });

  it('cancels an active download', async () => {
    mockedFetchDownloads.mockResolvedValueOnce([
      {
        id: 1,
        filename: 'Cancelable Widget.mp3',
        status: 'running',
        progress: 40,
        priority: 3
      }
    ]);
    mockedFetchDownloads.mockResolvedValue([
      {
        id: 1,
        filename: 'Cancelable Widget.mp3',
        status: 'cancelled',
        progress: 40,
        priority: 3
      }
    ]);
    mockedCancelDownload.mockResolvedValue();

    renderWithProviders(<DownloadWidget />, { toastFn: toastMock, route: '/dashboard' });

    const cancelButton = await screen.findByRole('button', { name: 'Abbrechen' });
    await userEvent.click(cancelButton);

    await waitFor(() => expect(mockedCancelDownload).toHaveBeenCalledWith('1'));
    await waitFor(() => expect(mockedFetchDownloads).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText('Cancelled')).toBeInTheDocument());
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Download abgebrochen' })
    );
  });

  it('retries a failed download', async () => {
    mockedFetchDownloads.mockResolvedValueOnce([
      { id: 2, filename: 'Retry Widget.mp3', status: 'failed', progress: 0, priority: 0 }
    ]);
    mockedFetchDownloads.mockResolvedValue([
      {
        id: 2,
        filename: 'Retry Widget.mp3',
        status: 'failed',
        progress: 0,
        priority: 0
      },
      {
        id: 3,
        filename: 'Retry Widget.mp3',
        status: 'queued',
        progress: 0,
        priority: 1
      }
    ]);
    mockedRetryDownload.mockResolvedValue({
      id: 3,
      filename: 'Retry Widget.mp3',
      status: 'queued',
      progress: 0,
      priority: 1
    });

    renderWithProviders(<DownloadWidget />, { toastFn: toastMock, route: '/dashboard' });

    const retryButton = await screen.findByRole('button', { name: 'Neu starten' });
    await userEvent.click(retryButton);

    await waitFor(() => expect(mockedRetryDownload).toHaveBeenCalledWith('2'));
    await waitFor(() => expect(mockedFetchDownloads).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getAllByText('Retry Widget.mp3').length).toBeGreaterThan(1));
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Download neu gestartet' })
    );
  });
});
