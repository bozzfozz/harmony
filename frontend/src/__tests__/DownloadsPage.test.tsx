import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DownloadsPage from '../pages/DownloadsPage';
import { renderWithProviders } from '../test-utils';
import {
  ApiError,
  cancelDownload,
  exportDownloads,
  getDownloads,
  retryDownload,
  startDownload,
  updateDownloadPriority
} from '../lib/api';

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  getDownloads: jest.fn(),
  startDownload: jest.fn(),
  cancelDownload: jest.fn(),
  retryDownload: jest.fn(),
  updateDownloadPriority: jest.fn(),
  exportDownloads: jest.fn()
}));

const mockedGetDownloads = getDownloads as jest.MockedFunction<typeof getDownloads>;
const mockedStartDownload = startDownload as jest.MockedFunction<typeof startDownload>;
const mockedCancelDownload = cancelDownload as jest.MockedFunction<typeof cancelDownload>;
const mockedRetryDownload = retryDownload as jest.MockedFunction<typeof retryDownload>;
const mockedUpdatePriority = updateDownloadPriority as jest.MockedFunction<typeof updateDownloadPriority>;
const mockedExportDownloads = exportDownloads as jest.MockedFunction<typeof exportDownloads>;

const toastMock = jest.fn();

describe('DownloadsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('filters downloads by status', async () => {
    mockedGetDownloads.mockResolvedValue([
      {
        id: 1,
        filename: 'Queued File.mp3',
        status: 'queued',
        progress: 10,
        priority: 1
      }
    ]);

    renderWithProviders(<DownloadsPage />, { toastFn: toastMock, route: '/downloads' });

    expect(await screen.findByText('Queued File.mp3')).toBeInTheDocument();
    expect(mockedGetDownloads).toHaveBeenCalledWith({ includeAll: false, status: undefined });

    mockedGetDownloads.mockResolvedValueOnce([
      {
        id: 2,
        filename: 'Failed File.mp3',
        status: 'failed',
        progress: 0,
        priority: 2
      }
    ]);

    await userEvent.selectOptions(screen.getByLabelText('Status'), ['failed']);

    await waitFor(() =>
      expect(mockedGetDownloads).toHaveBeenLastCalledWith({ includeAll: false, status: 'failed' })
    );
    expect(await screen.findByText('Failed File.mp3')).toBeInTheDocument();
  });

  it('updates priority via the inline editor', async () => {
    mockedGetDownloads.mockResolvedValue([
      {
        id: 3,
        filename: 'Priority File.mp3',
        status: 'queued',
        progress: 0,
        priority: 0
      }
    ]);
    mockedUpdatePriority.mockResolvedValue({
      id: 3,
      filename: 'Priority File.mp3',
      status: 'queued',
      progress: 0,
      priority: 5
    } as never);

    renderWithProviders(<DownloadsPage />, { toastFn: toastMock, route: '/downloads' });

    const priorityInput = await screen.findByLabelText('Priorität für Priority File.mp3');
    await userEvent.clear(priorityInput);
    await userEvent.type(priorityInput, '5');
    await userEvent.click(screen.getByRole('button', { name: 'Setzen' }));

    await waitFor(() => expect(mockedUpdatePriority).toHaveBeenCalledWith({ id: '3', priority: 5 }));
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ title: 'Priorität aktualisiert' }));
  });

  it('displays retry statuses with readable labels', async () => {
    mockedGetDownloads.mockResolvedValue([
      {
        id: 4,
        filename: 'Retried File.mp3',
        status: 'download_retry_scheduled',
        progress: 0,
        priority: 1
      }
    ]);

    renderWithProviders(<DownloadsPage />, { toastFn: toastMock, route: '/downloads' });

    expect(await screen.findByText('Retried File.mp3')).toBeInTheDocument();
    expect(screen.getByText('Download Retry Scheduled')).toBeInTheDocument();
  });

  it('exports downloads as CSV', async () => {
    mockedGetDownloads.mockResolvedValue([]);
    const blob = new Blob(['id,filename'], { type: 'text/csv' });
    mockedExportDownloads.mockResolvedValue(blob);

    const createObjectURLSpy = jest.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    const revokeSpy = jest.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const clickSpy = jest.fn();
    const createElementSpy = jest.spyOn(document, 'createElement').mockReturnValue({
      href: '',
      download: '',
      click: clickSpy,
      remove: jest.fn()
    } as unknown as HTMLAnchorElement);

    renderWithProviders(<DownloadsPage />, { toastFn: toastMock, route: '/downloads' });

    const csvButton = await screen.findByRole('button', { name: 'Export CSV' });
    await userEvent.click(csvButton);

    await waitFor(() => expect(mockedExportDownloads).toHaveBeenCalledWith('csv', { status: undefined }));
    expect(createObjectURLSpy).toHaveBeenCalledWith(blob);
    expect(clickSpy).toHaveBeenCalled();

    createObjectURLSpy.mockRestore();
    revokeSpy.mockRestore();
    createElementSpy.mockRestore();
  });

  it('shows a blocked toast when the backend rejects download requests with 503', async () => {
    mockedGetDownloads.mockResolvedValue([]);
    mockedStartDownload.mockRejectedValue(new ApiError({
      message: 'Credentials missing',
      status: 503,
      data: null,
      originalError: new Error('credentials missing')
    }));

    renderWithProviders(<DownloadsPage />, { toastFn: toastMock, route: '/downloads' });

    const input = await screen.findByLabelText('Track-ID');
    await userEvent.type(input, 'Song.mp3');

    const submitButton = screen.getByRole('button', { name: 'Download starten' });
    await userEvent.click(submitButton);

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: '❌ Zugangsdaten erforderlich' })
      )
    );
});
});
