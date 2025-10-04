import LibraryDownloads from '../pages/Library/LibraryDownloads';
import { renderWithProviders } from '../test-utils';
import { LIBRARY_POLL_INTERVAL_MS } from '../api/services/downloads';
import { useQuery } from '../lib/query';

type MockedUseQuery = jest.MockedFunction<typeof useQuery>;

type QueryOptions = {
  queryKey?: unknown;
  enabled?: boolean;
  refetchInterval?: number | false;
  onError?: (error: unknown) => void;
};

jest.mock('../lib/query', () => {
  const actual = jest.requireActual('../lib/query');
  return {
    ...actual,
    useQuery: jest.fn()
  };
});

const mockedUseQuery = useQuery as MockedUseQuery;

const createQueryResult = () => ({
  data: [],
  error: undefined,
  isLoading: false,
  isError: false,
  refetch: jest.fn()
});

describe('Library tab gating', () => {
  beforeEach(() => {
    mockedUseQuery.mockReset();
  });

  it('verhindert Datenabfragen in inaktiven Tabs', () => {
    const capturedOptions: QueryOptions[] = [];
    mockedUseQuery.mockImplementation((options: QueryOptions) => {
      capturedOptions.push(options);
      return createQueryResult();
    });

    renderWithProviders(<LibraryDownloads isActive={false} />);

    const listOptions = capturedOptions.find((option) => {
      const queryKey = option.queryKey as unknown[] | undefined;
      return Array.isArray(queryKey) && queryKey.length === 3;
    });
    expect(listOptions).toBeDefined();
    expect(listOptions?.enabled).toBe(false);
    expect(listOptions?.refetchInterval).toBe(false);
  });

  it('aktiviert Polling nur im aktiven Tab', () => {
    const capturedOptions: QueryOptions[] = [];
    mockedUseQuery.mockImplementation((options: QueryOptions) => {
      capturedOptions.push(options);
      return createQueryResult();
    });

    renderWithProviders(<LibraryDownloads isActive />);

    const listOptions = capturedOptions.find((option) => {
      const queryKey = option.queryKey as unknown[] | undefined;
      return Array.isArray(queryKey) && queryKey.length === 3;
    });
    expect(listOptions).toBeDefined();
    expect(listOptions?.enabled).toBe(true);
    expect(listOptions?.refetchInterval).toBe(LIBRARY_POLL_INTERVAL_MS);
  });

  it('unterdrückt Fehler-Toasts wenn der Tab inaktiv ist', () => {
    const toastSpy = jest.fn();
    let onError: ((error: unknown) => void) | undefined;
    mockedUseQuery.mockImplementation((options: QueryOptions) => {
      const queryKey = options.queryKey as unknown[] | undefined;
      if (Array.isArray(queryKey) && queryKey.length === 3) {
        onError = options.onError;
      }
      return createQueryResult();
    });

    renderWithProviders(<LibraryDownloads isActive={false} />, { toastFn: toastSpy });

    expect(typeof onError).toBe('function');
    onError?.(new Error('Testfehler'));
    expect(toastSpy).not.toHaveBeenCalled();
  });
});
