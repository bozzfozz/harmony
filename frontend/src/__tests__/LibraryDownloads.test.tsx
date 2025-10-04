import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LibraryDownloads from '../pages/Library/LibraryDownloads';
import { renderWithProviders } from '../test-utils';
import { ApiError } from '../api/client';
import { exportDownloads, getDownloads, startDownload, updateDownloadPriority } from '../api/services/downloads';

jest.mock('../api/services/downloads', () => ({
  ...jest.requireActual('../api/services/downloads'),
  getDownloads: jest.fn(),
  startDownload: jest.fn(),
  updateDownloadPriority: jest.fn(),
  exportDownloads: jest.fn()
}));

const mockedGetDownloads = getDownloads as jest.MockedFunction<typeof getDownloads>;
const mockedStartDownload = startDownload as jest.MockedFunction<typeof startDownload>;
const mockedUpdatePriority = updateDownloadPriority as jest.MockedFunction<typeof updateDownloadPriority>;
const mockedExportDownloads = exportDownloads as jest.MockedFunction<typeof exportDownloads>;

const toastMock = jest.fn();

describe('LibraryDownloads', () => {
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

    renderWithProviders(<LibraryDownloads />, { toastFn: toastMock, route: '/library?tab=downloads' });

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

    const statusTrigger = await screen.findByRole('combobox', { name: 'Status' });
    await userEvent.click(statusTrigger);
    await userEvent.click(await screen.findByRole('option', { name: 'Fehlgeschlagen' }));

    await waitFor(() =>
      expect(mockedGetDownloads).toHaveBeenLastCalledWith({ includeAll: true, status: 'failed' })
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

    renderWithProviders(<LibraryDownloads />, { toastFn: toastMock, route: '/library?tab=downloads' });

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

    renderWithProviders(<LibraryDownloads />, { toastFn: toastMock, route: '/library?tab=downloads' });

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

    renderWithProviders(<LibraryDownloads />, { toastFn: toastMock, route: '/library?tab=downloads' });

    const csvButton = await screen.findByRole('button', { name: 'Export CSV' });
    await userEvent.click(csvButton);

    await waitFor(() => expect(mockedExportDownloads).toHaveBeenCalledWith('csv', { status: undefined }));
    expect(createObjectURLSpy).toHaveBeenCalledWith(blob);
    expect(clickSpy).toHaveBeenCalled();

    createObjectURLSpy.mockRestore();
    revokeSpy.mockRestore();
    createElementSpy.mockRestore();
  });

  it('submits download payload with username and file metadata', async () => {
    mockedGetDownloads.mockResolvedValue([]);
    mockedStartDownload.mockResolvedValue({
      id: 10,
      filename: 'Song.mp3',
      status: 'queued',
      progress: 0,
      priority: 0,
      username: 'SoulUser'
    } as never);

    renderWithProviders(<LibraryDownloads />, { toastFn: toastMock, route: '/library?tab=downloads' });

    const usernameInput = await screen.findByLabelText('Soulseek-Benutzername');
    const fileInput = screen.getByLabelText('Datei oder Track');

    await userEvent.type(usernameInput, 'SoulUser');
    await userEvent.type(fileInput, 'Song.mp3');

    await userEvent.click(screen.getByRole('button', { name: 'Download starten' }));

    await waitFor(() =>
      expect(mockedStartDownload).toHaveBeenCalledWith({
        username: 'SoulUser',
        files: [
          {
            filename: 'Song.mp3',
            name: 'Song.mp3',
            source: 'library_manual'
          }
        ]
      })
    );

    await waitFor(() => expect(fileInput).toHaveValue(''));
  });

  it('derives username from soulseek uri input when omitted', async () => {
    mockedGetDownloads.mockResolvedValue([]);
    mockedStartDownload.mockResolvedValue({
      id: 11,
      filename: 'folder/song.mp3',
      status: 'queued',
      progress: 0,
      priority: 0,
      username: 'DerivedUser'
    } as never);

    renderWithProviders(<LibraryDownloads />, { toastFn: toastMock, route: '/library?tab=downloads' });

    const usernameInput = await screen.findByLabelText('Soulseek-Benutzername');
    const fileInput = screen.getByLabelText('Datei oder Track');

    expect(usernameInput).toHaveValue('');

    await userEvent.type(fileInput, 'soulseek://DerivedUser/folder/song.mp3');
    await userEvent.click(screen.getByRole('button', { name: 'Download starten' }));

    await waitFor(() =>
      expect(mockedStartDownload).toHaveBeenCalledWith({
        username: 'DerivedUser',
        files: [
          {
            filename: 'folder/song.mp3',
            name: 'soulseek://DerivedUser/folder/song.mp3',
            source: 'library_manual'
          }
        ]
      })
    );

    await waitFor(() => expect(usernameInput).toHaveValue('DerivedUser'));
  });

  it('shows a blocked toast when the backend rejects download requests with 503', async () => {
    mockedGetDownloads.mockResolvedValue([]);
    mockedStartDownload.mockRejectedValue(
      new ApiError({
        code: 'CREDENTIALS_MISSING',
        message: 'Credentials missing',
        status: 503,
        details: null,
        cause: new Error('credentials missing')
      })
    );

    renderWithProviders(<LibraryDownloads />, { toastFn: toastMock, route: '/library?tab=downloads' });

    const usernameInput = await screen.findByLabelText('Soulseek-Benutzername');
    const fileInput = screen.getByLabelText('Datei oder Track');

    await userEvent.type(usernameInput, 'SoulUser');
    await userEvent.type(fileInput, 'Song.mp3');

    const submitButton = screen.getByRole('button', { name: 'Download starten' });
    await userEvent.click(submitButton);

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: '❌ Zugangsdaten erforderlich' })
      )
    );
});
});
