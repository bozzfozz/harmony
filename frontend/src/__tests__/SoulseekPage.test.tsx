import { screen } from '@testing-library/react';

import SoulseekPage from '../pages/SoulseekPage';
import { renderWithProviders } from '../test-utils';
import { useQuery } from '../lib/query';
import type { IntegrationsData } from '../api/services/soulseek';
import type {
  SoulseekConfigurationEntry,
  NormalizedSoulseekDownload
} from '../api/services/soulseek';
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

const joinQueryKey = (queryKey: unknown): string => {
  if (Array.isArray(queryKey)) {
    return queryKey.join(':');
  }
  return String(queryKey);
};

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

    const downloadData: NormalizedSoulseekDownload[] = [
      {
        id: '42',
        filename: 'album-track.mp3',
        username: 'alice',
        state: 'failed',
        progress: 0.42,
        priority: 5,
        retryCount: 2,
        lastError: 'Timeout',
        createdAt: '2024-01-01T10:00:00Z',
        updatedAt: '2024-01-01T10:05:00Z',
        queuedAt: '2024-01-01T09:55:00Z',
        startedAt: null,
        completedAt: null,
        nextRetryAt: null,
        raw: {} as any
      }
    ];

    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      switch (key) {
        case 'soulseek:status':
          return createQueryResult({ data: statusData });
        case 'integrations:providers':
          return createQueryResult({ data: integrationData });
        case 'soulseek:configuration':
          return createQueryResult({ data: configurationData });
        case 'soulseek:uploads:active':
          return createQueryResult({ data: [] });
        case 'soulseek:downloads:active':
          return createQueryResult({ data: downloadData });
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
    expect(screen.getByText('album-track.mp3')).toBeInTheDocument();
    expect(screen.getByText('Priorität: 5')).toBeInTheDocument();
    expect(screen.getByText('2 Retries')).toBeInTheDocument();
    expect(screen.getByText('Fehler: Timeout')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('zeigt einen Fehlerhinweis, wenn Uploads nicht geladen werden können', () => {
    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      if (key === 'soulseek:uploads:active') {
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
      const key = joinQueryKey(queryKey);
      if (key === 'soulseek:uploads:active') {
        return createQueryResult({ isLoading: true });
      }
      return createQueryResult();
    });

    renderWithProviders(<SoulseekPage />, { route: '/soulseek' });

    expect(screen.getByText(/Uploads werden geladen/)).toBeInTheDocument();
  });

  it('zeigt einen Fehlerhinweis, wenn Downloads nicht geladen werden können', () => {
    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      if (key === 'soulseek:downloads:active') {
        return createQueryResult({ isError: true, error: new Error('boom') });
      }
      return createQueryResult();
    });

    renderWithProviders(<SoulseekPage />, { route: '/soulseek' });

    expect(screen.getByText('Downloads konnten nicht geladen werden.')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Erneut versuchen' })).not.toHaveLength(0);
  });

  it('zeigt den Ladezustand für Downloads an', () => {
    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      if (key === 'soulseek:downloads:active') {
        return createQueryResult({ isLoading: true });
      }
      return createQueryResult();
    });

    renderWithProviders(<SoulseekPage />, { route: '/soulseek' });

    expect(screen.getByText(/Downloads werden geladen/)).toBeInTheDocument();
  });

  it('informiert, wenn keine Downloads vorliegen', () => {
    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      if (key === 'soulseek:downloads:active') {
        return createQueryResult({ data: [] });
      }
      return createQueryResult();
    });

    renderWithProviders(<SoulseekPage />, { route: '/soulseek' });

    expect(screen.getByText(/Aktuell sind keine Downloads aktiv/)).toBeInTheDocument();
  });
});
