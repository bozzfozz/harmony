import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MatchingPage from '../pages/MatchingPage';
import { renderWithProviders } from '../test-utils';
import { getMatchingOverview } from '../api/services/matching';

jest.mock('../api/services/matching', () => ({
  getMatchingOverview: jest.fn()
}));

const mockedGetMatchingOverview = getMatchingOverview as jest.MockedFunction<typeof getMatchingOverview>;

describe('MatchingPage', () => {
  const toastMock = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('zeigt Workerstatus, Metriken und Eventverlauf an', async () => {
    mockedGetMatchingOverview.mockResolvedValue({
      worker: { status: 'stale', lastSeen: '2024-05-05T10:00:00Z', queueSize: 3, rawQueueSize: 3 },
      metrics: {
        lastAverageConfidence: 0.91,
        lastDiscarded: 1,
        savedTotal: 45,
        discardedTotal: 5
      },
      events: [
        {
          timestamp: '2024-05-05T10:30:00Z',
          stored: 2,
          discarded: 1,
          averageConfidence: 0.95,
          jobId: 'job-1',
          jobType: 'metadata'
        }
      ]
    });

    renderWithProviders(<MatchingPage />, { route: '/matching', toastFn: toastMock });

    expect(await screen.findByText('Matching-Worker')).toBeInTheDocument();
    expect(screen.getByText(/Ø Konfidenz/)).toBeInTheDocument();
    expect(screen.getByText('91.0 %')).toBeInTheDocument();
    expect(screen.getByText(/Die Matching-Queue enthält 3 offene Jobs/)).toBeInTheDocument();
    expect(screen.getByText(/seit einiger Zeit nicht gesehen/)).toBeInTheDocument();

    const eventHeading = await screen.findByText(/Charge vom/i);
    const eventItem = eventHeading.closest('li');
    expect(eventItem).not.toBeNull();
    if (eventItem) {
      expect(eventItem).toHaveTextContent('Teilweise gespeichert');
      expect(eventItem).toHaveTextContent('2 gespeichert');
      expect(eventItem).toHaveTextContent('1 verworfen');
    }
  });

  it('zeigt Fallbacks an, wenn keine Daten vorliegen', async () => {
    mockedGetMatchingOverview.mockResolvedValue({
      worker: { status: undefined, lastSeen: null, queueSize: null, rawQueueSize: null },
      metrics: {},
      events: []
    });

    renderWithProviders(<MatchingPage />, { route: '/matching', toastFn: toastMock });

    expect(await screen.findByText('Matching-Worker')).toBeInTheDocument();
    expect(screen.getByText('Keine Daten')).toBeInTheDocument();
    expect(screen.getByText(/Noch keine Matches bewertet/)).toBeInTheDocument();
    expect(screen.getByText(/Noch keine Matching-Läufe protokolliert/)).toBeInTheDocument();
  });

  it('meldet Fehlerzustände und erlaubt einen erneuten Versuch', async () => {
    mockedGetMatchingOverview.mockRejectedValue(new Error('kaputt'));

    renderWithProviders(<MatchingPage />, { route: '/matching', toastFn: toastMock });

    await waitFor(() => {
      expect(
        screen.getAllByText('Matching-Daten stehen derzeit nicht zur Verfügung.').length
      ).toBeGreaterThan(0);
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Matching-Daten konnten nicht geladen werden' })
    );

    mockedGetMatchingOverview.mockResolvedValueOnce({
      worker: { status: 'running', lastSeen: '2024-05-05T10:00:00Z', queueSize: 0, rawQueueSize: 0 },
      metrics: { lastAverageConfidence: 0.8, lastDiscarded: 0, savedTotal: 1, discardedTotal: 0 },
      events: []
    });

    const retryButtons = screen.getAllByRole('button', { name: /Erneut versuchen/ });
    const retryButton = retryButtons[0];
    await userEvent.click(retryButton);

    await waitFor(() => expect(mockedGetMatchingOverview).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('Matching-Worker')).toBeInTheDocument();
  });
});
