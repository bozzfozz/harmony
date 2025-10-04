import { screen } from '@testing-library/react';

import AppRoutes from '../routes';
import { renderWithProviders } from '../test-utils';
import {
  getIntegrations,
  getSoulseekConfiguration,
  getSoulseekStatus,
  getSoulseekUploads
} from '../api/services/soulseek';
import { getMatchingOverview } from '../api/services/matching';

jest.mock('../api/services/soulseek', () => ({
  getSoulseekStatus: jest.fn(),
  getSoulseekUploads: jest.fn(),
  getIntegrations: jest.fn(),
  getSoulseekConfiguration: jest.fn()
}));

jest.mock('../api/services/matching', () => ({
  getMatchingOverview: jest.fn()
}));

const mockedGetSoulseekStatus = getSoulseekStatus as jest.MockedFunction<typeof getSoulseekStatus>;
const mockedGetSoulseekUploads = getSoulseekUploads as jest.MockedFunction<typeof getSoulseekUploads>;
const mockedGetIntegrations = getIntegrations as jest.MockedFunction<typeof getIntegrations>;
const mockedGetSoulseekConfiguration = getSoulseekConfiguration as jest.MockedFunction<
  typeof getSoulseekConfiguration
>;
const mockedGetMatchingOverview = getMatchingOverview as jest.MockedFunction<typeof getMatchingOverview>;

describe('AppRoutes', () => {
  const renderWithRoute = (route: string) => renderWithProviders(<AppRoutes />, { route });

  beforeEach(() => {
    mockedGetSoulseekStatus.mockResolvedValue({ status: 'connected' });
    mockedGetSoulseekUploads.mockResolvedValue([]);
    mockedGetIntegrations.mockResolvedValue({ overall: 'ok', providers: [] });
    mockedGetSoulseekConfiguration.mockResolvedValue([]);
    mockedGetMatchingOverview.mockResolvedValue({
      worker: { status: 'running', lastSeen: '2024-05-05T10:00:00Z', queueSize: 0, rawQueueSize: 0 },
      metrics: {
        lastAverageConfidence: 0.92,
        lastDiscarded: 0,
        savedTotal: 12,
        discardedTotal: 3
      },
      events: []
    });
  });

  it('renders the Soulseek page without redirecting', async () => {
    renderWithRoute('/soulseek');

    expect(screen.getByRole('heading', { name: /Soulseek/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/Verbindung wird geprüft/i)).toBeInTheDocument();
    expect(await screen.findByText(/Aktive Uploads/i)).toBeInTheDocument();
  });

  it('renders the Matching page without redirecting', async () => {
    renderWithRoute('/matching');

    expect(
      screen.getByRole('heading', { name: /Matching/i, level: 1 })
    ).toBeInTheDocument();
    expect(await screen.findByText('Worker-Status')).toBeInTheDocument();
    expect(screen.getByText(/Ø Konfidenz/)).toBeInTheDocument();
    expect(screen.getByText(/Noch keine Matching-Läufe/)).toBeInTheDocument();
  });
});
