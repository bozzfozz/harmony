import { screen } from '@testing-library/react';

import SoulseekPage from '../pages/SoulseekPage';
import { renderWithProviders } from '../test-utils';
import { useQuery } from '../lib/query';
import type { IntegrationsData } from '../api/services/soulseek';
import type { SoulseekConfigurationEntry } from '../api/services/soulseek';
import type { SoulseekStatusResponse } from '../api/types';

jest.mock('../lib/query', () => {
  const actual = jest.requireActual('../lib/query');
  return {
    ...actual,
    useQuery: jest.fn()
  };
});

const mockedUseQuery = useQuery as jest.MockedFunction<typeof useQuery>;

type QueryResult<T> = {
  data: T | undefined;
  error: unknown;
  isLoading: boolean;
  isError: boolean;
  refetch: jest.Mock;
};

const createQueryResult = <T,>(overrides: Partial<QueryResult<T>> = {}): QueryResult<T> => ({
  data: undefined,
  error: undefined,
  isLoading: false,
  isError: false,
  refetch: jest.fn(),
  ...overrides
});

describe('SoulseekPage', () => {
  beforeEach(() => {
    mockedUseQuery.mockReset();
  });

  it('zeigt Status, Konfiguration und Uploads an', () => {
    const statusData: SoulseekStatusResponse = { status: 'connected' };
    const integrationData: IntegrationsData = {
      overall: 'degraded',
      providers: [
        {
          name: 'soulseek',
          status: 'down',
          details: { reason: 'missing_credentials' }
        }
      ]
    };
    const configurationData: SoulseekConfigurationEntry[] = [
      {
        key: 'SLSKD_URL',
        label: 'Basis-URL',
        value: 'https://slskd.example',
        displayValue: 'https://slskd.example',
        present: true,
        masked: false
      }
    ];

    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const [, scope] = queryKey as [string, string];
      switch (scope) {
        case 'status':
          return createQueryResult({ data: statusData });
        case 'providers':
          return createQueryResult({ data: integrationData });
        case 'configuration':
          return createQueryResult({ data: configurationData });
        case 'uploads':
          return createQueryResult({ data: [] });
        default:
          return createQueryResult();
      }
    });

    renderWithProviders(<SoulseekPage />, { route: '/soulseek' });

    expect(screen.getByRole('heading', { name: /Soulseek/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByText('Basis-URL')).toBeInTheDocument();
    expect(screen.getByLabelText(/Status: Verbunden/i)).toBeInTheDocument();
    expect(screen.getByText(/Verbunden/)).toBeInTheDocument();
    expect(screen.getByText(/missing_credentials/)).toBeInTheDocument();
    expect(screen.getByText(/Aktuell sind keine Uploads aktiv/)).toBeInTheDocument();
  });

  it('zeigt einen Fehlerhinweis, wenn Uploads nicht geladen werden können', () => {
    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const [, scope] = queryKey as [string, string];
      if (scope === 'uploads') {
        return createQueryResult({ isError: true, error: new Error('boom') });
      }
      return createQueryResult();
    });

    renderWithProviders(<SoulseekPage />, { route: '/soulseek' });

    expect(screen.getByText('Uploads konnten nicht geladen werden.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Erneut versuchen' })).toBeInTheDocument();
  });

  it('zeigt Ladezustände an, solange Daten angefordert werden', () => {
    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const [, scope] = queryKey as [string, string];
      if (scope === 'uploads') {
        return createQueryResult({ isLoading: true });
      }
      return createQueryResult();
    });

    renderWithProviders(<SoulseekPage />, { route: '/soulseek' });

    expect(screen.getByText(/Uploads werden geladen/)).toBeInTheDocument();
  });
});
