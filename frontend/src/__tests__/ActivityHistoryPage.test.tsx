import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ActivityHistoryPage from '../pages/ActivityHistoryPage';
import { renderWithProviders } from '../test-utils';
import { exportActivityHistory, fetchActivityHistory } from '../lib/api';

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  fetchActivityHistory: jest.fn(),
  exportActivityHistory: jest.fn()
}));

const mockedFetchActivityHistory = fetchActivityHistory as jest.MockedFunction<typeof fetchActivityHistory>;
const mockedExportActivityHistory = exportActivityHistory as jest.MockedFunction<typeof exportActivityHistory>;
const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

describe('ActivityHistoryPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: jest.fn(() => 'blob:mock')
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: jest.fn()
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: originalCreateObjectURL
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: originalRevokeObjectURL
    });
  });

  it('renders activity entries and supports pagination', async () => {
    mockedFetchActivityHistory
      .mockResolvedValueOnce({
        items: [
          { timestamp: '2024-03-18T12:00:00Z', type: 'sync', status: 'completed', details: { runs: 2 } },
          { timestamp: '2024-03-18T11:55:00Z', type: 'download', status: 'ok', details: { id: 42 } }
        ],
        total_count: 45
      })
      .mockResolvedValueOnce({
        items: [
          { timestamp: '2024-03-18T11:50:00Z', type: 'worker', status: 'started', details: { worker: 'sync' } }
        ],
        total_count: 45
      });

    const user = userEvent.setup();
    renderWithProviders(<ActivityHistoryPage />);

    await waitFor(() => expect(mockedFetchActivityHistory).toHaveBeenCalledTimes(1));
    expect(mockedFetchActivityHistory).toHaveBeenCalledWith(20, 0, undefined, undefined);
    expect(await screen.findByText('sync')).toBeInTheDocument();

    const nextButton = screen.getByRole('button', { name: 'Weiter' });
    await user.click(nextButton);

    await waitFor(() => expect(mockedFetchActivityHistory).toHaveBeenCalledTimes(2));
    expect(mockedFetchActivityHistory).toHaveBeenLastCalledWith(20, 20, undefined, undefined);
    await waitFor(() => expect(screen.getByText('worker')).toBeInTheDocument());
  });

  it('applies type and status filters', async () => {
    mockedFetchActivityHistory
      .mockResolvedValueOnce({
        items: [
          { timestamp: '2024-03-18T12:00:00Z', type: 'sync', status: 'completed' },
          { timestamp: '2024-03-18T11:59:00Z', type: 'download', status: 'failed' }
        ],
        total_count: 2
      })
      .mockResolvedValueOnce({
        items: [{ timestamp: '2024-03-18T11:58:00Z', type: 'download', status: 'failed' }],
        total_count: 1
      })
      .mockResolvedValueOnce({
        items: [{ timestamp: '2024-03-18T11:57:00Z', type: 'download', status: 'failed' }],
        total_count: 1
      });

    const user = userEvent.setup();
    renderWithProviders(<ActivityHistoryPage />);

    const typeSelect = await screen.findByLabelText('Activity-Typ filtern');
    await user.selectOptions(typeSelect, 'download');
    await waitFor(() => expect(mockedFetchActivityHistory).toHaveBeenLastCalledWith(20, 0, 'download', undefined));

    const statusSelect = screen.getByLabelText('Activity-Status filtern');
    await user.selectOptions(statusSelect, 'failed');
    await waitFor(() => expect(mockedFetchActivityHistory).toHaveBeenLastCalledWith(20, 0, 'download', 'failed'));
    expect(await screen.findAllByText('download')).toHaveLength(1);
  });

  it('shows toast and inline message on error', async () => {
    const toastMock = jest.fn();
    mockedFetchActivityHistory.mockRejectedValue(new Error('network error'));

    renderWithProviders(<ActivityHistoryPage />, { toastFn: toastMock });

    await waitFor(() => expect(toastMock).toHaveBeenCalled());
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Activity History nicht erreichbar' })
    );
    expect(await screen.findByText('Die Activity History konnte nicht geladen werden.')).toBeInTheDocument();
  });

  it('exports filtered results as JSON and CSV', async () => {
    mockedFetchActivityHistory.mockResolvedValue({
      items: [
        { timestamp: '2024-03-18T12:00:00Z', type: 'download', status: 'failed', details: { id: 1 } }
      ],
      total_count: 1
    });
    mockedExportActivityHistory
      .mockResolvedValueOnce(new Blob(['[]'], { type: 'application/json' }))
      .mockResolvedValueOnce(new Blob(['id,timestamp'], { type: 'text/csv' }));

    const user = userEvent.setup();
    const toastMock = jest.fn();
    const originalCreateElement = document.createElement.bind(document);
    const createElementSpy = jest.spyOn(document, 'createElement');
    renderWithProviders(<ActivityHistoryPage />, { toastFn: toastMock });

    const typeSelect = await screen.findByLabelText('Activity-Typ filtern');
    await user.selectOptions(typeSelect, 'download');
    const statusSelect = screen.getByLabelText('Activity-Status filtern');
    await user.selectOptions(statusSelect, 'failed');

    const anchor = originalCreateElement('a');
    const clickSpy = jest.spyOn(anchor, 'click');
    createElementSpy.mockImplementation((tagName: string) => {
      if (tagName.toLowerCase() === 'a') {
        return anchor;
      }
      return originalCreateElement(tagName);
    });

    const jsonButton = screen.getByRole('button', { name: 'Export JSON' });
    await user.click(jsonButton);

    await waitFor(() => expect(mockedExportActivityHistory).toHaveBeenCalledTimes(1));
    expect(mockedExportActivityHistory).toHaveBeenCalledWith('json', {
      type: 'download',
      status: 'failed'
    });
    expect(clickSpy).toHaveBeenCalled();

    const csvButton = screen.getByRole('button', { name: 'Export CSV' });
    await user.click(csvButton);

    await waitFor(() => expect(mockedExportActivityHistory).toHaveBeenCalledTimes(2));
    expect(mockedExportActivityHistory).toHaveBeenLastCalledWith('csv', {
      type: 'download',
      status: 'failed'
    });
    expect(clickSpy).toHaveBeenCalledTimes(2);
    expect(toastMock).not.toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Export fehlgeschlagen' })
    );
  });

  it('shows toast when export fails', async () => {
    mockedFetchActivityHistory.mockResolvedValue({ items: [], total_count: 0 });
    mockedExportActivityHistory.mockRejectedValue(new Error('timeout'));
    const toastMock = jest.fn();

    const user = userEvent.setup();
    renderWithProviders(<ActivityHistoryPage />, { toastFn: toastMock });

    const jsonButton = await screen.findByRole('button', { name: 'Export JSON' });
    await user.click(jsonButton);

    await waitFor(() => expect(mockedExportActivityHistory).toHaveBeenCalled());
    await waitFor(() => expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Export fehlgeschlagen' })
    ));
  });
});
