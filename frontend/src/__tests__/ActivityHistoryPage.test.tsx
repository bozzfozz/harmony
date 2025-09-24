import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ActivityHistoryPage from '../pages/ActivityHistoryPage';
import { renderWithProviders } from '../test-utils';
import { fetchActivityHistory } from '../lib/api';

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  fetchActivityHistory: jest.fn()
}));

const mockedFetchActivityHistory = fetchActivityHistory as jest.MockedFunction<typeof fetchActivityHistory>;

describe('ActivityHistoryPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
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
});
