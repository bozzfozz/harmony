import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DashboardPage from '../pages/DashboardPage';
import { renderWithProviders } from '../test-utils';
import { getActivityFeed, getSystemStatus, triggerManualSync } from '../api/services/system';

type GetSystemStatusMock = jest.MockedFunction<typeof getSystemStatus>;
type GetActivityFeedMock = jest.MockedFunction<typeof getActivityFeed>;
type TriggerManualSyncMock = jest.MockedFunction<typeof triggerManualSync>;

jest.mock('../api/services/system', () => ({
  ...jest.requireActual('../api/services/system'),
  getSystemStatus: jest.fn(),
  getActivityFeed: jest.fn(),
  triggerManualSync: jest.fn()
}));

const mockedGetSystemStatus = getSystemStatus as GetSystemStatusMock;
const mockedGetActivityFeed = getActivityFeed as GetActivityFeedMock;
const mockedTriggerManualSync = triggerManualSync as TriggerManualSyncMock;

const toastMock = jest.fn();

describe('DashboardPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('zeigt Service-Status, Worker-Karten und Aktivitätsfeed', async () => {
    mockedGetSystemStatus.mockResolvedValue({
      connections: { spotify: 'ok', plex: 'fail', soulseek: 'blocked' },
      workers: {
        importer: { status: 'running', queue_size: 2, last_seen: '2024-05-05T10:00:00Z' },
        downloader: { status: 'stopped', queue_size: 0, last_seen: '2024-05-05T09:55:00Z' }
      }
    });
    mockedGetActivityFeed.mockResolvedValue([
      {
        timestamp: '2024-05-05T10:10:00Z',
        type: 'download_retry',
        status: 'running',
        details: { filename: 'Track.mp3', attempts: 2 }
      }
    ]);

    renderWithProviders(<DashboardPage />, { toastFn: toastMock, route: '/dashboard' });

    expect(await screen.findByText('Service-Verbindungen')).toBeInTheDocument();
    expect(screen.getByText('Spotify')).toBeInTheDocument();
    expect(screen.getByText('Verbunden')).toBeInTheDocument();
    expect(screen.getByText('Plex')).toBeInTheDocument();
    expect(screen.getByText('Fehlgeschlagen')).toBeInTheDocument();
    expect(screen.getByText('Soulseek')).toBeInTheDocument();
    expect(screen.getByText('Blockiert')).toBeInTheDocument();

    expect(await screen.findByTestId('worker-card-importer')).toBeInTheDocument();
    expect(screen.getByText('Importer')).toBeInTheDocument();

    expect(await screen.findByText('Download-Wiederholung')).toBeInTheDocument();
    expect(screen.getByText(/Track.mp3/)).toBeInTheDocument();
  });

  it('startet einen manuellen Sync und zeigt eine Erfolgsmeldung', async () => {
    mockedGetSystemStatus.mockResolvedValue({ connections: {}, workers: {} });
    mockedGetActivityFeed.mockResolvedValue([]);
    mockedTriggerManualSync.mockResolvedValue();

    renderWithProviders(<DashboardPage />, { toastFn: toastMock, route: '/dashboard' });

    const button = await screen.findByRole('button', { name: /Sync auslösen/ });
    await userEvent.click(button);

    await waitFor(() => expect(mockedTriggerManualSync).toHaveBeenCalled());
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: '✅ Sync gestartet' })
    );
  });
});
