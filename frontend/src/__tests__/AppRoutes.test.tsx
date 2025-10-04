import { screen } from '@testing-library/react';

import AppRoutes from '../routes';
import { renderWithProviders } from '../test-utils';
import {
  getIntegrationsReport,
  getSoulseekConfiguration,
  getSoulseekStatus,
  getSoulseekUploads
} from '../api/services/soulseek';

jest.mock('../api/services/soulseek', () => ({
  getSoulseekStatus: jest.fn(),
  getSoulseekUploads: jest.fn(),
  getIntegrationsReport: jest.fn(),
  getSoulseekConfiguration: jest.fn()
}));

const mockedGetSoulseekStatus = getSoulseekStatus as jest.MockedFunction<typeof getSoulseekStatus>;
const mockedGetSoulseekUploads = getSoulseekUploads as jest.MockedFunction<typeof getSoulseekUploads>;
const mockedGetIntegrationsReport = getIntegrationsReport as jest.MockedFunction<typeof getIntegrationsReport>;
const mockedGetSoulseekConfiguration = getSoulseekConfiguration as jest.MockedFunction<
  typeof getSoulseekConfiguration
>;

describe('AppRoutes', () => {
  const renderWithRoute = (route: string) => renderWithProviders(<AppRoutes />, { route });

  beforeEach(() => {
    mockedGetSoulseekStatus.mockResolvedValue({ status: 'connected' });
    mockedGetSoulseekUploads.mockResolvedValue([]);
    mockedGetIntegrationsReport.mockResolvedValue({ overall: 'ok', providers: [] });
    mockedGetSoulseekConfiguration.mockResolvedValue([]);
  });

  it('renders the Soulseek page without redirecting', async () => {
    renderWithRoute('/soulseek');

    expect(screen.getByRole('heading', { name: /Soulseek/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/Verbindung wird geprüft/i)).toBeInTheDocument();
    expect(await screen.findByText(/Aktive Uploads/i)).toBeInTheDocument();
  });

  it('renders the Matching page without redirecting', () => {
    renderWithRoute('/matching');

    expect(
      screen.getByRole('heading', { name: /Matching/i, level: 1 })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Abgleichsstatus, vorgeschlagene Zuordnungen/i)
    ).toBeInTheDocument();
  });
});
