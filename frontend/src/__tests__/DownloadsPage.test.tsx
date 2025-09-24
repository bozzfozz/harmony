import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import DownloadsPage from '../pages/DownloadsPage';
import { renderWithProviders } from '../test-utils';
import { fetchActiveDownloads, startDownload } from '../lib/api';

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  fetchActiveDownloads: jest.fn(),
  startDownload: jest.fn()
}));

const mockedFetchDownloads = fetchActiveDownloads as jest.MockedFunction<typeof fetchActiveDownloads>;
const mockedStartDownload = startDownload as jest.MockedFunction<typeof startDownload>;

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
});
