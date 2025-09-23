import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react';

type QueryKeyPart = string | number | boolean | null | undefined;
type QueryKey = QueryKeyPart[];

const serializeKey = (key: QueryKey) => JSON.stringify(key);

type Subscriber = () => void;

class QueryClient {
  private subscribers = new Map<string, Set<Subscriber>>();

  subscribe(queryKey: QueryKey, callback: Subscriber) {
    const key = serializeKey(queryKey);
    if (!this.subscribers.has(key)) {
      this.subscribers.set(key, new Set());
    }
    const listeners = this.subscribers.get(key)!;
    listeners.add(callback);
    return () => {
      listeners.delete(callback);
      if (listeners.size === 0) {
        this.subscribers.delete(key);
      }
    };
  }

  invalidateQueries(options?: { queryKey?: QueryKey }) {
    if (options?.queryKey) {
      const key = serializeKey(options.queryKey);
      this.subscribers.get(key)?.forEach((listener) => listener());
      return;
    }
    this.subscribers.forEach((listeners) => listeners.forEach((listener) => listener()));
  }
}

const QueryClientContext = createContext<QueryClient | null>(null);

interface QueryClientProviderProps {
  client: QueryClient;
  children: ReactNode;
}

const QueryClientProvider = ({ client, children }: QueryClientProviderProps) => (
  <QueryClientContext.Provider value={client}>{children}</QueryClientContext.Provider>
);

const useQueryClient = () => {
  const client = useContext(QueryClientContext);
  if (!client) {
    throw new Error('useQueryClient must be used within a QueryClientProvider');
  }
  return client;
};

interface UseQueryOptions<TData> {
  queryKey: QueryKey;
  queryFn: () => Promise<TData>;
  refetchInterval?: number;
  onError?: (error: unknown) => void;
}

interface UseQueryResult<TData> {
  data: TData | undefined;
  error: unknown;
  isLoading: boolean;
  isError: boolean;
  refetch: () => Promise<void>;
}

const useQuery = <TData,>({ queryKey, queryFn, refetchInterval, onError }: UseQueryOptions<TData>): UseQueryResult<TData> => {
  const client = useQueryClient();
  const [data, setData] = useState<TData | undefined>(undefined);
  const [error, setError] = useState<unknown>(undefined);
  const [isLoading, setIsLoading] = useState(true);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const execute = useCallback(async () => {
    setIsLoading(true);
    setError(undefined);
    try {
      const result = await queryFn();
      if (mountedRef.current) {
        setData(result);
        setIsLoading(false);
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(err);
        setIsLoading(false);
      }
      onError?.(err);
    }
  }, [queryFn, onError]);

  useEffect(() => {
    execute();
  }, [execute]);

  useEffect(() => {
    const unsubscribe = client.subscribe(queryKey, execute);
    return unsubscribe;
  }, [client, execute, queryKey]);

  useEffect(() => {
    if (!refetchInterval) {
      return;
    }
    const timer = window.setInterval(() => {
      execute();
    }, refetchInterval);
    return () => window.clearInterval(timer);
  }, [execute, refetchInterval]);

  const refetch = useCallback(async () => {
    await execute();
  }, [execute]);

  return useMemo(
    () => ({
      data,
      error,
      isLoading,
      isError: Boolean(error),
      refetch
    }),
    [data, error, isLoading, refetch]
  );
};

interface UseMutationOptions<TInput, TOutput> {
  mutationFn: (input: TInput) => Promise<TOutput>;
  onSuccess?: (data: TOutput, input: TInput) => void;
  onError?: (error: unknown, input: TInput) => void;
}

interface UseMutationResult<TInput, TOutput> {
  mutate: (input: TInput) => Promise<void>;
  mutateAsync: (input: TInput) => Promise<TOutput>;
  reset: () => void;
  data: TOutput | undefined;
  error: unknown;
  isPending: boolean;
}

const useMutation = <TInput, TOutput>({
  mutationFn,
  onError,
  onSuccess
}: UseMutationOptions<TInput, TOutput>): UseMutationResult<TInput, TOutput> => {
  const [data, setData] = useState<TOutput | undefined>(undefined);
  const [error, setError] = useState<unknown>(undefined);
  const [isPending, setIsPending] = useState(false);

  const execute = useCallback(
    async (input: TInput) => {
      setIsPending(true);
      setError(undefined);
      try {
        const result = await mutationFn(input);
        setData(result);
        setIsPending(false);
        onSuccess?.(result, input);
        return result;
      } catch (err) {
        setError(err);
        setIsPending(false);
        onError?.(err, input);
        throw err;
      }
    },
    [mutationFn, onError, onSuccess]
  );

  const mutate = useCallback(
    async (input: TInput) => {
      await execute(input);
    },
    [execute]
  );

  const reset = useCallback(() => {
    setData(undefined);
    setError(undefined);
    setIsPending(false);
  }, []);

  return {
    mutate,
    mutateAsync: execute,
    reset,
    data,
    error,
    isPending
  };
};

export { QueryClient, QueryClientProvider, useQueryClient, useQuery, useMutation };
