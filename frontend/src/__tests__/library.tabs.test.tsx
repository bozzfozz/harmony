import LibraryDownloads from '../pages/Library/LibraryDownloads';
import { renderWithProviders } from '../test-utils';
import { LIBRARY_POLL_INTERVAL_MS } from '../lib/api';
import { useQuery } from '../lib/query';

type MockedUseQuery = jest.MockedFunction<typeof useQuery>;

jest.mock('../lib/query', () => {
  const actual = jest.requireActual('../lib/query');
  return {
    ...actual,
    useQuery: jest.fn()
  };
});

const mockedUseQuery = useQuery as MockedUseQuery;

describe('Library tab gating', () => {
  beforeEach(() => {
    mockedUseQuery.mockReset();
  });

  it('verhindert Datenabfragen in inaktiven Tabs', () => {
    const capturedOptions: unknown[] = [];
    mockedUseQuery.mockImplementation((options: any) => {
      capturedOptions.push(options);
      return {
        data: [],
        error: undefined,
        isLoading: false,
        isError: false,
        refetch: jest.fn()
      };
    });

    renderWithProviders(<LibraryDownloads isActive={false} />);

    expect(capturedOptions).toHaveLength(1);
    const options = capturedOptions[0] as { enabled?: boolean; refetchInterval?: number | false };
    expect(options.enabled).toBe(false);
    expect(options.refetchInterval).toBe(false);
  });

  it('aktiviert Polling nur im aktiven Tab', () => {
    const capturedOptions: unknown[] = [];
    mockedUseQuery.mockImplementation((options: any) => {
      capturedOptions.push(options);
      return {
        data: [],
        error: undefined,
        isLoading: false,
        isError: false,
        refetch: jest.fn()
      };
    });

    renderWithProviders(<LibraryDownloads isActive />);

    expect(capturedOptions).toHaveLength(1);
    const options = capturedOptions[0] as { enabled?: boolean; refetchInterval?: number | false };
    expect(options.enabled).toBe(true);
    expect(options.refetchInterval).toBe(LIBRARY_POLL_INTERVAL_MS);
  });

  it('unterdrückt Fehler-Toasts wenn der Tab inaktiv ist', () => {
    const toastSpy = jest.fn();
    let onError: ((error: unknown) => void) | undefined;
    mockedUseQuery.mockImplementation((options: any) => {
      onError = options.onError;
      return {
        data: [],
        error: undefined,
        isLoading: false,
        isError: false,
        refetch: jest.fn()
      };
    });

    renderWithProviders(<LibraryDownloads isActive={false} />, { toastFn: toastSpy });

    expect(typeof onError).toBe('function');
    onError?.(new Error('Testfehler'));
    expect(toastSpy).not.toHaveBeenCalled();
  });
});
