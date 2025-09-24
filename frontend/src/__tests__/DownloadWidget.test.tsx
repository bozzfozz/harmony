import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import DownloadWidget from '../components/DownloadWidget';
import { renderWithProviders } from '../test-utils';
import { fetchDownloads } from '../lib/api';

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  fetchDownloads: jest.fn()
}));

const mockedFetchDownloads = fetchDownloads as jest.MockedFunction<typeof fetchDownloads>;

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
        progress: 45
      },
      {
        id: 2,
        filename: 'Track Two.mp3',
        status: 'queued',
        progress: 10
      }
    ]);

    renderWithProviders(<DownloadWidget />, { toastFn: toastMock, route: '/dashboard' });

    expect(await screen.findByText('Track One.mp3')).toBeInTheDocument();
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('45%')).toBeInTheDocument();
    expect(mockedFetchDownloads).toHaveBeenCalledWith(5);
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
      { id: 1, filename: 'A.mp3', status: 'running', progress: 60 },
      { id: 2, filename: 'B.mp3', status: 'running', progress: 40 },
      { id: 3, filename: 'C.mp3', status: 'running', progress: 20 },
      { id: 4, filename: 'D.mp3', status: 'running', progress: 10 },
      { id: 5, filename: 'E.mp3', status: 'running', progress: 5 },
      { id: 6, filename: 'F.mp3', status: 'running', progress: 2 }
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
      { id: 1, filename: 'A.mp3', status: 'running', progress: 60 },
      { id: 2, filename: 'B.mp3', status: 'running', progress: 40 },
      { id: 3, filename: 'C.mp3', status: 'running', progress: 20 },
      { id: 4, filename: 'D.mp3', status: 'running', progress: 10 },
      { id: 5, filename: 'E.mp3', status: 'running', progress: 5 }
    ]);

    renderWithProviders(<DownloadWidget />, { toastFn: toastMock, route: '/dashboard' });

    expect(await screen.findByText('A.mp3')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Alle anzeigen' })).not.toBeInTheDocument());
  });
});
