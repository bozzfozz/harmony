import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SoulseekPage from '../pages/SoulseekPage';
import { renderWithProviders } from '../test-utils';
import { useQuery } from '../lib/query';
import {
  requeueSoulseekDownload,
  SoulseekRequeueError,
  type IntegrationsData,
  SoulseekConfigurationEntry,
  NormalizedSoulseekDownload,
  type SoulseekDownloadsResult
} from '../api/services/soulseek';
import type { SoulseekStatusResponse } from '../api/types';

jest.mock('../lib/query', () => {
  const actual = jest.requireActual('../lib/query');
  return {
    ...actual,
    useQuery: jest.fn()
  };
});

jest.mock('../api/services/soulseek', () => {
  const actual = jest.requireActual('../api/services/soulseek');
  return {
    ...actual,
    requeueSoulseekDownload: jest.fn()
  };
});

const mockedUseQuery = useQuery as jest.MockedFunction<typeof useQuery>;
const mockedRequeueSoulseekDownload =
  requeueSoulseekDownload as jest.MockedFunction<typeof requeueSoulseekDownload>;

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

const createDownloadsResult = (
  downloads: NormalizedSoulseekDownload[],
  retryableStates: string[] = ['failed']
): SoulseekDownloadsResult => ({
  downloads,
  retryableStates
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
    mockedRequeueSoulseekDownload.mockReset();
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

    const downloadsResult = createDownloadsResult(
      [
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
      ],
      ['failed', 'completed']
    );

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
          return createQueryResult({ data: downloadsResult });
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
        return createQueryResult({ data: createDownloadsResult([]) });
      }
      return createQueryResult();
    });

    renderWithProviders(<SoulseekPage />, { route: '/soulseek' });

    expect(screen.getByText(/Aktuell sind keine Downloads aktiv/)).toBeInTheDocument();
  });

  it('deaktiviert den Retry-Button für Dead-Letter-Downloads', () => {
    const downloadsResult = createDownloadsResult([
      {
        id: '42',
        filename: 'album-track.mp3',
        username: 'alice',
        state: 'dead_letter',
        progress: 0,
        priority: null,
        retryCount: 0,
        lastError: 'Permanent failure',
        createdAt: null,
        updatedAt: null,
        queuedAt: null,
        startedAt: null,
        completedAt: null,
        nextRetryAt: null,
        raw: {} as any
      }
    ]);

    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      if (key === 'soulseek:downloads:active') {
        return createQueryResult({ data: downloadsResult });
      }
      return createQueryResult();
    });

    renderWithProviders(<SoulseekPage />, { route: '/soulseek' });

    const badge = screen.getByRole('status', { name: /wartet auf eingriff/i });
    expect(badge).toHaveClass('bg-rose-100');

    const retryButton = screen.getByRole('button', { name: 'Retry' });
    expect(retryButton).toBeDisabled();
  });

  it('aktiviert Retries für vom Backend freigegebene Zustände', () => {
    const downloadsResult = createDownloadsResult(
      [
        {
          id: '42',
          filename: 'album-track.mp3',
          username: 'alice',
          state: 'failed',
          progress: 0,
          priority: null,
          retryCount: 0,
          lastError: null,
          createdAt: null,
          updatedAt: null,
          queuedAt: null,
          startedAt: null,
          completedAt: null,
          nextRetryAt: null,
          raw: {} as any
        },
        {
          id: '84',
          filename: 'completed-track.mp3',
          username: 'bob',
          state: 'completed',
          progress: 1,
          priority: 1,
          retryCount: 0,
          lastError: null,
          createdAt: null,
          updatedAt: null,
          queuedAt: null,
          startedAt: null,
          completedAt: '2024-01-02T12:00:00Z',
          nextRetryAt: null,
          raw: {} as any
        }
      ],
      ['failed', 'completed']
    );

    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      if (key === 'soulseek:downloads:active') {
        return createQueryResult({ data: downloadsResult });
      }
      return createQueryResult();
    });

    renderWithProviders(<SoulseekPage />, { route: '/soulseek' });

    const completedRow = screen.getByText('completed-track.mp3').closest('tr');
    expect(completedRow).not.toBeNull();
    if (!completedRow) {
      throw new Error('completed row missing');
    }

    expect(within(completedRow).getByRole('button', { name: 'Retry' })).toBeEnabled();
  });

  it('plant fehlgeschlagene Downloads erneut ein und aktualisiert die Liste', async () => {
    const refetchMock = jest.fn().mockResolvedValue(undefined);
    const toastMock = jest.fn();
    const statusData: SoulseekStatusResponse = { status: 'connected' };
    const downloadsResult = createDownloadsResult([
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
    ]);

    let resolveRequeue: (() => void) | undefined;
    mockedRequeueSoulseekDownload.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveRequeue = resolve;
        })
    );

    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      switch (key) {
        case 'soulseek:status':
          return createQueryResult({ data: statusData });
        case 'soulseek:downloads:active':
          return createQueryResult({ data: downloadsResult, refetch: refetchMock });
        default:
          return createQueryResult();
      }
    });

    const user = userEvent.setup();
    renderWithProviders(<SoulseekPage />, { route: '/soulseek', toastFn: toastMock });

    const retryButton = screen.getByRole('button', { name: 'Retry' });
    await user.click(retryButton);

    expect(mockedRequeueSoulseekDownload).toHaveBeenCalledWith('42');
    expect(await screen.findByRole('button', { name: /Wird erneut gestartet/i })).toBeDisabled();

    resolveRequeue?.();

    await waitFor(() => {
      expect(refetchMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Download erneut eingeplant',
        description: 'album-track.mp3 wird erneut heruntergeladen.'
      })
    );
  });

  it('zeigt einen Konflikt-Hinweis, wenn der Download in der Dead-Letter-Queue liegt', async () => {
    const toastMock = jest.fn();
    mockedRequeueSoulseekDownload.mockRejectedValue(
      new SoulseekRequeueError(
        'Der Download befindet sich in der Dead-Letter-Queue und muss manuell geprüft werden.',
        { code: 'CONFLICT', status: 409 }
      )
    );

    const downloadsResult = createDownloadsResult([
      {
        id: '42',
        filename: 'album-track.mp3',
        username: 'alice',
        state: 'failed',
        progress: 0,
        priority: null,
        retryCount: 0,
        lastError: null,
        createdAt: null,
        updatedAt: null,
        queuedAt: null,
        startedAt: null,
        completedAt: null,
        nextRetryAt: null,
        raw: {} as any
      }
    ]);

    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      if (key === 'soulseek:downloads:active') {
        return createQueryResult({ data: downloadsResult });
      }
      return createQueryResult();
    });

    const user = userEvent.setup();
    renderWithProviders(<SoulseekPage />, { route: '/soulseek', toastFn: toastMock });

    await user.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Retry fehlgeschlagen',
          description: 'Der Download befindet sich in der Dead-Letter-Queue und muss manuell geprüft werden.',
          variant: 'destructive'
        })
      );
    });
  });

  it('meldet allgemeine Fehler beim Requeue-Versuch', async () => {
    const toastMock = jest.fn();
    mockedRequeueSoulseekDownload.mockRejectedValue(new Error('kaputt'));

    const downloadsResult = createDownloadsResult([
      {
        id: '42',
        filename: 'album-track.mp3',
        username: 'alice',
        state: 'failed',
        progress: 0,
        priority: null,
        retryCount: 0,
        lastError: null,
        createdAt: null,
        updatedAt: null,
        queuedAt: null,
        startedAt: null,
        completedAt: null,
        nextRetryAt: null,
        raw: {} as any
      }
    ]);

    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      if (key === 'soulseek:downloads:active') {
        return createQueryResult({ data: downloadsResult });
      }
      return createQueryResult();
    });

    const user = userEvent.setup();
    renderWithProviders(<SoulseekPage />, { route: '/soulseek', toastFn: toastMock });

    await user.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Retry fehlgeschlagen',
          description: 'Der Download konnte nicht erneut eingeplant werden.',
          variant: 'destructive'
        })
      );
    });
  });
});
