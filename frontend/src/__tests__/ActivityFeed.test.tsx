import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ActivityFeed from '../components/ActivityFeed';
import { renderWithProviders } from '../test-utils';
import { getActivityFeed } from '../lib/api';

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  getActivityFeed: jest.fn()
}));

const mockedGetActivityFeed = getActivityFeed as jest.MockedFunction<typeof getActivityFeed>;

const toastMock = jest.fn();

describe('ActivityFeed', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders activity entries with icons and status colours', async () => {
    mockedGetActivityFeed.mockResolvedValue([
      {
        timestamp: '2024-03-18T12:00:00Z',
        type: 'sync',
        status: 'completed',
        details: { counters: { tracks_synced: 3 } }
      },
      {
        timestamp: '2024-03-18T11:59:00Z',
        type: 'search',
        status: 'partial',
        details: { query: 'Boards of Canada', matches: { spotify: 5, plex: 1 } }
      },
      { timestamp: '2024-03-18T11:58:00Z', type: 'download', status: 'failed' }
    ]);

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    const entries = await screen.findAllByTestId('activity-entry');
    expect(entries).toHaveLength(3);

    const syncEntry = entries[0];
    expect(within(syncEntry).getByText('Synchronisierung')).toBeInTheDocument();
    expect(within(syncEntry).getByText('🔄')).toBeInTheDocument();
    expect(within(syncEntry).getByText('Abgeschlossen')).toHaveClass('bg-emerald-100');

    const searchEntry = entries[1];
    expect(within(searchEntry).getByText('Suche')).toBeInTheDocument();
    expect(within(searchEntry).getByText('🔍')).toBeInTheDocument();
    expect(within(searchEntry).getByText('Teilweise')).toHaveClass('bg-amber-100');

    const downloadEntry = entries[2];
    expect(within(downloadEntry).getByText('Download')).toBeInTheDocument();
    expect(within(downloadEntry).getByText('⬇')).toBeInTheDocument();
    expect(within(downloadEntry).getByText('Fehlgeschlagen')).toHaveClass('bg-rose-100');
  });

  it('renders blocked events with red icon and label', async () => {
    mockedGetActivityFeed.mockResolvedValue([
      { timestamp: '2024-03-18T12:10:00Z', type: 'sync', status: 'sync_blocked' },
      { timestamp: '2024-03-18T12:09:00Z', type: 'download', status: 'download_blocked' },
      {
        timestamp: '2024-03-18T12:08:00Z',
        type: 'autosync',
        status: 'autosync_blocked',
        details: { trigger: 'manual' }
      }
    ]);

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    const entries = await screen.findAllByTestId('activity-entry');
    expect(entries).toHaveLength(3);

    const syncEntry = entries[0];
    expect(within(syncEntry).getByText('Synchronisierung')).toBeInTheDocument();
    expect(within(syncEntry).getByText('⛔')).toBeInTheDocument();
    expect(within(syncEntry).getByText('Blockiert')).toHaveClass('bg-rose-100');

    const downloadEntry = entries[1];
    expect(within(downloadEntry).getByText('Download')).toBeInTheDocument();
    expect(within(downloadEntry).getByText('⛔')).toBeInTheDocument();
    expect(within(downloadEntry).getByText('Blockiert')).toHaveClass('bg-rose-100');

    const autosyncEntry = entries[2];
    expect(within(autosyncEntry).getByText('AutoSync')).toBeInTheDocument();
    expect(within(autosyncEntry).getByText('⛔')).toBeInTheDocument();
    expect(within(autosyncEntry).getByText('Blockiert')).toHaveClass('bg-rose-100');
  });

  it('renders worker events with dedicated icons, colours and details', async () => {
    const user = userEvent.setup();
    mockedGetActivityFeed.mockResolvedValue([
      {
        timestamp: '2024-03-18T12:04:00Z',
        type: 'worker',
        status: 'started',
        details: { worker: 'sync' }
      },
      {
        timestamp: '2024-03-18T12:03:00Z',
        type: 'worker',
        status: 'stopped',
        details: { worker: 'scan', timestamp: '2024-03-18T12:02:50Z', reason: 'shutdown' }
      },
      {
        timestamp: '2024-03-18T12:02:00Z',
        type: 'worker',
        status: 'stale',
        details: {
          worker: 'matching',
          last_seen: '2024-03-18T12:00:00Z',
          threshold_seconds: 60,
          elapsed_seconds: 120
        }
      },
      {
        timestamp: '2024-03-18T12:01:00Z',
        type: 'worker',
        status: 'restarted',
        details: { worker: 'playlist', previous_status: 'stopped' }
      }
    ]);

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    const startedEntry = screen.getByText('Worker Sync').closest('[data-testid="activity-entry"]');
    expect(startedEntry).not.toBeNull();
    expect(within(startedEntry as HTMLElement).getByText('▶️')).toBeInTheDocument();
    expect(within(startedEntry as HTMLElement).getByText('Gestartet')).toHaveClass('bg-emerald-100');

    const stoppedEntry = screen.getByText('Worker Scan').closest('[data-testid="activity-entry"]');
    expect(stoppedEntry).not.toBeNull();
    expect(within(stoppedEntry as HTMLElement).getByText('⏹')).toBeInTheDocument();
    expect(within(stoppedEntry as HTMLElement).getByText('Gestoppt')).toHaveClass('bg-slate-100');

    const restartedEntry = screen.getByText('Worker Playlist').closest('[data-testid="activity-entry"]');
    expect(restartedEntry).not.toBeNull();
    expect(within(restartedEntry as HTMLElement).getByText('🔄')).toBeInTheDocument();
    expect(within(restartedEntry as HTMLElement).getByText('Neu gestartet')).toHaveClass('bg-sky-100');

    const staleEntry = screen.getByText('Worker Matching').closest('[data-testid="activity-entry"]');
    expect(staleEntry).not.toBeNull();
    expect(within(staleEntry as HTMLElement).getByText('⚠️')).toBeInTheDocument();
    expect(within(staleEntry as HTMLElement).getByText('Veraltet')).toHaveClass('bg-amber-100');

    const summary = within(staleEntry as HTMLElement).getByText('Worker Matching');
    await user.click(summary.closest('summary') ?? summary);

    await waitFor(() => expect(within(staleEntry as HTMLElement).getByText(/Überwachung:/)).toBeInTheDocument());
    expect(within(staleEntry as HTMLElement).getByText(/Schwelle 60s/)).toBeInTheDocument();
  });

  it('notifies when no activities are available', async () => {
    mockedGetActivityFeed.mockResolvedValue([]);

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    await waitFor(() => expect(screen.getByText('Keine Aktivitäten vorhanden.')).toBeInTheDocument());
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Keine Activity-Daten' })
    );
  });

  it('shows toast on error', async () => {
    mockedGetActivityFeed.mockRejectedValue(new Error('network error'));

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    await waitFor(() => expect(toastMock).toHaveBeenCalled());
    expect(screen.getByText('Der Aktivitätsfeed ist derzeit nicht verfügbar.')).toBeInTheDocument();
  });

  it('renders sync details with counters and error tooltip', async () => {
    const user = userEvent.setup();
    mockedGetActivityFeed.mockResolvedValue([
      {
        timestamp: '2024-03-18T12:00:00Z',
        type: 'sync',
        status: 'completed',
        details: {
          sources: ['spotify', 'plex'],
          counters: { tracks_synced: 12, errors: 1 },
          errors: [{ source: 'plex', message: 'plex offline' }]
        }
      }
    ]);

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    const entry = await screen.findByTestId('activity-entry');
    const summary = within(entry).getByText('Synchronisierung');
    await user.click(summary.closest('summary') ?? summary);

    await waitFor(() => expect(within(entry).getByText(/Quellen:/)).toBeInTheDocument());
    expect(within(entry).getByText(/Spotify, Plex/)).toBeInTheDocument();
    expect(within(entry).getByText(/Tracks Synced/)).toBeInTheDocument();
    expect(within(entry).getByText(/Errors/)).toBeInTheDocument();

    const errorBadge = within(entry).getByText(/Fehlerdetails/);
    expect(errorBadge).toHaveAttribute('title', expect.stringContaining('Plex: plex offline'));
  });

  it('renders search details with query and per source matches', async () => {
    const user = userEvent.setup();
    mockedGetActivityFeed.mockResolvedValue([
      {
        timestamp: '2024-03-18T12:01:00Z',
        type: 'search',
        status: 'completed',
        details: {
          query: 'Boards of Canada',
          matches: { spotify: 4, plex: 1, soulseek: 2 }
        }
      }
    ]);

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    const entry = await screen.findByTestId('activity-entry');
    const summary = within(entry).getByText('Suche');
    await user.click(summary.closest('summary') ?? summary);

    await waitFor(() => expect(within(entry).getByText(/Suchanfrage:/)).toBeInTheDocument());
    expect(within(entry).getByText('Boards of Canada')).toBeInTheDocument();
    expect(within(entry).getByText(/Spotify/)).toBeInTheDocument();
    expect(within(entry).getByText(/Plex/)).toBeInTheDocument();
    expect(within(entry).getByText(/Soulseek/)).toBeInTheDocument();
  });

  it('toggles accordion visibility for details', async () => {
    const user = userEvent.setup();
    mockedGetActivityFeed.mockResolvedValue([
      {
        timestamp: '2024-03-18T12:02:00Z',
        type: 'search',
        status: 'completed',
        details: { query: 'Aphex Twin', matches: { spotify: 2 } }
      }
    ]);

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    const entry = await screen.findByTestId('activity-entry');
    const summary = within(entry).getByText('Suche');
    const detailsElement = entry.querySelector('details') ?? entry;

    expect(detailsElement).not.toHaveAttribute('open');
    await user.click(summary.closest('summary') ?? summary);
    await waitFor(() => expect(detailsElement).toHaveAttribute('open'));
    await user.click(summary.closest('summary') ?? summary);
    await waitFor(() => expect(detailsElement).not.toHaveAttribute('open'));
  });

  it('filters events by selected type', async () => {
    const user = userEvent.setup();
    mockedGetActivityFeed.mockResolvedValue([
      { timestamp: '2024-03-18T12:10:00Z', type: 'sync', status: 'completed' },
      { timestamp: '2024-03-18T12:09:00Z', type: 'download', status: 'completed' },
      { timestamp: '2024-03-18T12:08:00Z', type: 'metadata', status: 'running' },
      { timestamp: '2024-03-18T12:07:00Z', type: 'worker_started', status: 'started' }
    ]);

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    const filterSelect = await screen.findByLabelText('Event-Typ');
    expect(filterSelect).toBeInTheDocument();

    await waitFor(() => expect(screen.getAllByTestId('activity-entry')).toHaveLength(4));

    await user.selectOptions(filterSelect, 'download');

    await waitFor(() => {
      const filteredEntries = screen.getAllByTestId('activity-entry');
      expect(filteredEntries).toHaveLength(1);
      expect(within(filteredEntries[0]).getByText('Download')).toBeInTheDocument();
    });

    await user.selectOptions(filterSelect, 'all');

    await waitFor(() => expect(screen.getAllByTestId('activity-entry')).toHaveLength(4));
  });

  it('keeps the empty state when no activities are present', async () => {
    mockedGetActivityFeed.mockResolvedValue([]);

    renderWithProviders(<ActivityFeed />, { toastFn: toastMock });

    const filterSelect = await screen.findByLabelText('Event-Typ');
    expect(filterSelect).toBeDisabled();

    await waitFor(() => expect(screen.getByText('Keine Aktivitäten vorhanden.')).toBeInTheDocument());
  });
});
