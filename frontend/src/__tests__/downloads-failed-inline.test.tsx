import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import LibraryDownloads from '../pages/Library/LibraryDownloads';
import { renderWithProviders } from '../test-utils';
import {
  ApiError,
  DownloadEntry,
  DownloadStats,
  ClearDownloadVariables,
  RetryDownloadVariables,
  RetryAllFailedResponse,
  getDownloads,
  useClearDownload,
  useDownloadStats,
  useRetryAllFailed,
  useRetryDownload
} from '../lib/api';
import { useQuery } from '../lib/query';

jest.mock('../lib/api', () => {
  const actual = jest.requireActual('../lib/api');
  return {
    ...actual,
    getDownloads: jest.fn(),
    useDownloadStats: jest.fn(),
    useRetryDownload: jest.fn(),
    useClearDownload: jest.fn(),
    useRetryAllFailed: jest.fn()
  };
});

jest.mock('../lib/query', () => {
  const actual = jest.requireActual('../lib/query');
  return {
    ...actual,
    useQuery: jest.fn()
  };
});

const mockedGetDownloads = getDownloads as jest.MockedFunction<typeof getDownloads>;
const mockedUseDownloadStats = useDownloadStats as jest.MockedFunction<typeof useDownloadStats>;
const mockedUseRetryDownload = useRetryDownload as jest.MockedFunction<typeof useRetryDownload>;
const mockedUseClearDownload = useClearDownload as jest.MockedFunction<typeof useClearDownload>;
const mockedUseRetryAllFailed = useRetryAllFailed as jest.MockedFunction<typeof useRetryAllFailed>;
const mockedUseQuery = useQuery as jest.MockedFunction<typeof useQuery>;

type QueryResult<TData> = {
  data: TData;
  error: unknown;
  isLoading: boolean;
  isError: boolean;
  refetch: () => Promise<void>;
};

const createMutationResult = <TInput, TOutput>() => {
  const mutate = jest.fn(async (_input: TInput) => undefined);
  const mutateAsync = jest.fn(async (_input: TInput) => ({} as TOutput));
  const result = {
    mutate,
    mutateAsync,
    reset: jest.fn(),
    data: undefined as TOutput | undefined,
    error: undefined as unknown,
    isPending: false
  };

  return { mutate, mutateAsync, result };
};

const createRetryDownloadMutation = () => {
  const { mutate, mutateAsync, result } = createMutationResult<RetryDownloadVariables, DownloadEntry>();
  return {
    mutate,
    mutateAsync,
    result: result as ReturnType<typeof useRetryDownload>
  };
};

const createClearDownloadMutation = () => {
  const { mutate, mutateAsync, result } = createMutationResult<ClearDownloadVariables, void>();
  return {
    mutate,
    mutateAsync,
    result: result as ReturnType<typeof useClearDownload>
  };
};

const createRetryAllFailedMutation = () => {
  const mutate = jest.fn(async () => undefined);
  const mutateAsync = jest.fn(async () => ({ requeued: 0, skipped: 0 } as RetryAllFailedResponse));
  const result = {
    mutate,
    mutateAsync,
    reset: jest.fn(),
    data: undefined as RetryAllFailedResponse | undefined,
    error: undefined as unknown,
    isPending: false,
    isSupported: true
  } as ReturnType<typeof useRetryAllFailed>;
  return { mutate, mutateAsync, result };
};

interface MockQueryOptions {
  queryKey: unknown;
  queryFn: () => Promise<unknown>;
  onError?: (error: unknown) => void;
}

const createQueryResponse = <TData,>(data: TData, overrides: Partial<QueryResult<TData>> = {}): QueryResult<TData> => ({
  data,
  error: overrides.error ?? undefined,
  isLoading: overrides.isLoading ?? false,
  isError: overrides.isError ?? false,
  refetch: overrides.refetch ?? (async () => undefined)
});

const toastMock = jest.fn();

const renderDownloads = () =>
  renderWithProviders(<LibraryDownloads />, { toastFn: toastMock, route: '/library?tab=downloads' });

describe('downloads failed inline controls', () => {
  let downloadsRows: DownloadEntry[];
  let stats: DownloadStats;
  let downloadsError: unknown | null;
  let downloadsRefetch: jest.Mock<Promise<void>, []>;

  beforeEach(() => {
    jest.clearAllMocks();
    toastMock.mockClear();

    downloadsRows = [];
    stats = { failed: 0 };
    downloadsError = null;
    downloadsRefetch = jest.fn().mockResolvedValue(undefined);

    mockedUseDownloadStats.mockReturnValue({
      data: stats,
      isLoading: false,
      error: undefined,
      isError: false,
      refetch: jest.fn()
    });

    mockedUseRetryDownload.mockReturnValue(createRetryDownloadMutation().result);
    mockedUseClearDownload.mockReturnValue(createClearDownloadMutation().result);
    mockedUseRetryAllFailed.mockReturnValue(createRetryAllFailedMutation().result);

    mockedUseQuery.mockImplementation((options: MockQueryOptions) => {
      const queryKey = options.queryKey as unknown[];
      if (Array.isArray(queryKey) && queryKey.length === 3) {
        if (downloadsError) {
          options.onError?.(downloadsError);
          return createQueryResponse([], { error: downloadsError, isError: true, refetch: downloadsRefetch });
        }
        if (typeof options.queryFn === 'function') {
          void options.queryFn().catch(() => undefined);
        }
        return createQueryResponse(downloadsRows, { refetch: downloadsRefetch });
      }
      if (Array.isArray(queryKey) && queryKey.length === 2 && queryKey[1] === 'stats') {
        return createQueryResponse(stats, { refetch: jest.fn().mockResolvedValue(undefined) });
      }
      throw new Error('Unexpected query key');
    });
  });

  it('renders_failed_badge_and_navigates_to_failed_filter', async () => {
    downloadsRows = [
      {
        id: 20,
        filename: 'Queued Song.mp3',
        status: 'queued',
        progress: 10,
        priority: 1
      }
    ];
    stats = { failed: 2 };
    mockedUseDownloadStats.mockReturnValue({
      data: stats,
      isLoading: false,
      error: undefined,
      isError: false,
      refetch: jest.fn()
    });
    mockedGetDownloads.mockResolvedValue(downloadsRows);

    renderDownloads();

    expect(await screen.findByText('Queued Song.mp3')).toBeInTheDocument();
    expect(mockedGetDownloads).toHaveBeenCalledWith({ includeAll: false, status: undefined });

    downloadsRows = [
      {
        id: 21,
        filename: 'Failed Song.mp3',
        status: 'failed',
        progress: 0,
        priority: 0
      }
    ];

    const badge = screen.getByRole('button', { name: 'Fehlgeschlagen: 2' });
    const user = userEvent.setup();
    await user.click(badge);

    await waitFor(() =>
      expect(mockedGetDownloads).toHaveBeenLastCalledWith({ includeAll: true, status: 'failed' })
    );
    expect(screen.getByLabelText('Status filtern')).toHaveValue('failed');
    expect(await screen.findByText('Failed Song.mp3')).toBeInTheDocument();
  });

  it('row_retry_triggers_mutation_and_refreshes_list', async () => {
    const retryMutation = createRetryDownloadMutation();
    mockedUseRetryDownload.mockReturnValue(retryMutation.result);

    downloadsRows = [
      {
        id: 9,
        filename: 'Failed Track.mp3',
        status: 'failed',
        progress: 0,
        priority: 0
      }
    ];
    stats = { failed: 1 };
    mockedUseDownloadStats.mockReturnValue({
      data: stats,
      isLoading: false,
      error: undefined,
      isError: false,
      refetch: jest.fn()
    });
    mockedGetDownloads.mockResolvedValue(downloadsRows);

    renderDownloads();

    expect(await screen.findByText('Failed Track.mp3')).toBeInTheDocument();
    const retryButton = screen.getByRole('button', { name: 'Neu starten' });

    const user = userEvent.setup();
    await user.click(retryButton);

    expect(retryMutation.mutate).toHaveBeenCalledWith({ id: '9', filename: 'Failed Track.mp3' });
  });

  it('row_clear_deletes_item_and_refreshes_list', async () => {
    const clearMutation = createClearDownloadMutation();
    mockedUseClearDownload.mockReturnValue(clearMutation.result);

    downloadsRows = [
      {
        id: 11,
        filename: 'Old Failed Track.mp3',
        status: 'failed',
        progress: 0,
        priority: 0
      }
    ];
    stats = { failed: 1 };
    mockedUseDownloadStats.mockReturnValue({
      data: stats,
      isLoading: false,
      error: undefined,
      isError: false,
      refetch: jest.fn()
    });
    mockedGetDownloads.mockResolvedValue(downloadsRows);

    renderDownloads();

    expect(await screen.findByText('Old Failed Track.mp3')).toBeInTheDocument();
    const clearButton = screen.getByRole('button', { name: 'Entfernen' });

    const user = userEvent.setup();
    await user.click(clearButton);

    expect(clearMutation.mutate).toHaveBeenCalledWith({ id: '11', filename: 'Old Failed Track.mp3' });
  });

  it('retry_all_failed_calls_endpoint_and_updates_badge', async () => {
    const retryAllMutation = createRetryAllFailedMutation();
    mockedUseRetryAllFailed.mockReturnValue(retryAllMutation.result);

    downloadsRows = [
      {
        id: 30,
        filename: 'Any Track.mp3',
        status: 'failed',
        progress: 0,
        priority: 0
      }
    ];
    stats = { failed: 3 };
    mockedUseDownloadStats.mockReturnValue({
      data: stats,
      isLoading: false,
      error: undefined,
      isError: false,
      refetch: jest.fn()
    });
    mockedGetDownloads.mockResolvedValue(downloadsRows);

    const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);

    renderDownloads();

    const retryAllButton = await screen.findByRole('button', {
      name: 'Alle fehlgeschlagenen erneut versuchen'
    });

    const user = userEvent.setup();
    await user.click(retryAllButton);

    expect(confirmSpy).toHaveBeenCalled();
    expect(retryAllMutation.mutate).toHaveBeenCalledTimes(1);

    confirmSpy.mockRestore();
  });

  it('handles_error_envelopes_without_toast_spam', async () => {
    const error = new ApiError({
      message: 'Backend down',
      status: 503,
      data: null,
      originalError: new Error('DEPENDENCY_ERROR')
    });
    error.markHandled();

    downloadsError = error;

    renderDownloads();

    await waitFor(() => expect(toastMock).not.toHaveBeenCalled());
    expect(screen.getByText('Downloads konnten nicht geladen werden.')).toBeInTheDocument();
  });
});
