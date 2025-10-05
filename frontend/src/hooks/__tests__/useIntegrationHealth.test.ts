import { renderHook } from '@testing-library/react';

import { useIntegrationHealth } from '../useIntegrationHealth';
import { useQuery } from '../../lib/query';
import type { SystemStatusResponse } from '../../api/types';
import type { IntegrationsData } from '../../api/services/soulseek';

jest.mock('../../lib/query', () => {
  const actual = jest.requireActual('../../lib/query');
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

describe('useIntegrationHealth', () => {
  beforeEach(() => {
    mockedUseQuery.mockReset();
  });

  it('marks services as degraded when either health query errors', () => {
    const systemStatus: SystemStatusResponse = {
      status: 'ok',
      connections: {
        soulseek: 'ok',
        matching: 'ok'
      }
    };
    const integrations: IntegrationsData = {
      overall: 'ok',
      providers: [
        { name: 'soulseek', status: 'ok' },
        { name: 'matching', status: 'ok' }
      ]
    };

    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      if (key === 'system:status') {
        return createQueryResult<SystemStatusResponse>({
          data: systemStatus,
          error: new Error('downstream unavailable'),
          isError: true
        });
      }
      if (key === 'integrations:overview') {
        return createQueryResult<IntegrationsData>({
          data: integrations
        });
      }
      throw new Error(`Unexpected query key: ${key}`);
    });

    const { result } = renderHook(() => useIntegrationHealth());

    expect(result.current.services.soulseek.degraded).toBe(true);
    expect(result.current.services.soulseek.online).toBe(false);
    expect(result.current.services.matching.degraded).toBe(true);
    expect(result.current.services.matching.online).toBe(false);
  });

  it('flags services as degraded when payloads are missing after loading', () => {
    mockedUseQuery.mockImplementation(({ queryKey }) => {
      const key = joinQueryKey(queryKey);
      if (key === 'system:status') {
        return createQueryResult<SystemStatusResponse>({
          data: undefined,
          isLoading: false
        });
      }
      if (key === 'integrations:overview') {
        return createQueryResult<IntegrationsData>({
          data: undefined,
          isLoading: false
        });
      }
      throw new Error(`Unexpected query key: ${key}`);
    });

    const { result } = renderHook(() => useIntegrationHealth());

    expect(result.current.services.soulseek.degraded).toBe(true);
    expect(result.current.services.soulseek.online).toBe(false);
    expect(result.current.services.matching.degraded).toBe(true);
  });
});
