import { screen, waitFor } from '@testing-library/react';
import ActivityFeed from '../components/ActivityFeed';
import { renderWithProviders } from '../test-utils';
import { fetchActivityFeed } from '../lib/api';

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  fetchActivityFeed: jest.fn()
}));

const mockedFetchActivityFeed = fetchActivityFeed as jest.MockedFunction<typeof fetchActivityFeed>;

const toastMock = jest.fn();

describe('ActivityFeed', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders activity rows', async () => {
    mockedFetchActivityFeed.mockResolvedValue([
      { timestamp: '2024-03-18T12:00:00Z', type: 'sync', status: 'completed' },
      { timestamp: '2024-03-18T11:59:00Z', type: 'download', status: 'queued' }
    ]);

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    expect(await screen.findByText('Synchronisierung')).toBeInTheDocument();
    expect(screen.getByText('Download')).toBeInTheDocument();

    expect(screen.getByText('Abgeschlossen')).toHaveClass('bg-emerald-100');
    expect(screen.getByText('Wartend')).toHaveClass('bg-amber-100');
  });

  it('notifies when no activities are available', async () => {
    mockedFetchActivityFeed.mockResolvedValue([]);

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    await waitFor(() => expect(screen.getByText('Keine Aktivitäten vorhanden.')).toBeInTheDocument());
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Keine Activity-Daten' })
    );
  });

  it('shows toast on error', async () => {
    mockedFetchActivityFeed.mockRejectedValue(new Error('network error'));

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    await waitFor(() => expect(toastMock).toHaveBeenCalled());
    expect(screen.getByText('Der Aktivitätsfeed ist derzeit nicht verfügbar.')).toBeInTheDocument();
  });
});
