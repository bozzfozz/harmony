import { applyAuth, getAuthMode, resolveKey } from '../lib/auth';
import { API_BASE_PATH, API_BASE_URL, API_TIMEOUT_MS, REQUIRE_AUTH, USE_OPENAPI_CLIENT } from './config';
import type { ApiErrorBody } from './types';

export type ResponseType = 'json' | 'text' | 'blob' | 'void';

export interface RequestConfig {
  url: string;
  method?: string;
  params?: Record<string, unknown>;
  data?: unknown;
  headers?: HeadersInit | Record<string, string | undefined>;
  responseType?: ResponseType;
  signal?: AbortSignal;
  credentials?: RequestCredentials;
}

const ensureLeadingSlash = (path: string): string => (path.startsWith('/') ? path : `/${path}`);

const normalizedBasePath = (() => {
  if (!API_BASE_PATH) {
    return '';
  }
  const withSlash = API_BASE_PATH.startsWith('/') ? API_BASE_PATH : `/${API_BASE_PATH}`;
  return withSlash.replace(/\/+$/u, '');
})();

export const apiUrl = (path: string): string => {
  const normalizedPath = ensureLeadingSlash(path);
  if (!normalizedBasePath) {
    return normalizedPath;
  }
  if (normalizedPath === '/') {
    return normalizedBasePath || '/';
  }
  return `${normalizedBasePath}${normalizedPath}`;
};

const createRequestId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `req_${Math.random().toString(16).slice(2, 10)}${Date.now().toString(16)}`;
};

const buildUrl = (input: string, params?: Record<string, unknown>): URL => {
  if (/^https?:/iu.test(input)) {
    const url = new URL(input);
    if (params) {
      const search = new URLSearchParams(url.search);
      Object.entries(params).forEach(([key, value]) => {
        if (value === undefined || value === null) {
          return;
        }
        if (Array.isArray(value)) {
          value.forEach((entry) => {
            if (entry !== undefined && entry !== null) {
              search.append(key, String(entry));
            }
          });
        } else {
          search.set(key, String(value));
        }
      });
      url.search = search.toString();
    }
    return url;
  }

  const base = API_BASE_URL.replace(/\/+$/u, '');
  const normalizedPath = input === '/' ? '/' : ensureLeadingSlash(input);
  const pathWithBase = normalizedBasePath
    ? normalizedPath.startsWith(normalizedBasePath)
      ? normalizedPath
      : `${normalizedBasePath}${normalizedPath}`
    : normalizedPath;
  const url = new URL(`${base}${pathWithBase}`);
  if (params) {
    const search = new URLSearchParams(url.search);
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null) {
        return;
      }
      if (Array.isArray(value)) {
        value.forEach((entry) => {
          if (entry !== undefined && entry !== null) {
            search.append(key, String(entry));
          }
        });
      } else {
        search.set(key, String(value));
      }
    });
    url.search = search.toString();
  }
  return url;
};

const AUTH_REQUIRED_PAYLOAD = {
  ok: false,
  error: {
    code: 'AUTH_REQUIRED',
    message: 'API key missing'
  }
} as const;

export interface ApiErrorInit {
  code: string;
  message: string;
  status?: number;
  details?: unknown;
  requestId?: string | null;
  url?: string;
  method?: string;
  cause?: unknown;
  body?: unknown;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status?: number;
  readonly details?: unknown;
  readonly requestId?: string | null;
  readonly url?: string;
  readonly method?: string;
  readonly cause?: unknown;
  readonly body?: unknown;
  handled = false;

  constructor(init: ApiErrorInit) {
    super(init.message);
    this.name = 'ApiError';
    this.code = init.code;
    this.status = init.status;
    this.details = init.details;
    this.requestId = init.requestId;
    this.url = init.url;
    this.method = init.method;
    this.cause = init.cause;
    this.body = init.body;
  }

  markHandled() {
    this.handled = true;
  }
}

export interface ApiErrorContext {
  error: ApiError;
}

type ApiErrorSubscriber = (context: ApiErrorContext) => void;

const apiErrorSubscribers = new Set<ApiErrorSubscriber>();

export const subscribeToApiErrors = (subscriber: ApiErrorSubscriber) => {
  apiErrorSubscribers.add(subscriber);
  return () => {
    apiErrorSubscribers.delete(subscriber);
  };
};

const notifyApiError = (error: ApiError) => {
  apiErrorSubscribers.forEach((subscriber) => subscriber({ error }));
};

const redirectToSettings = () => {
  if (typeof window === 'undefined') {
    return;
  }
  if (window.location.pathname === '/settings') {
    return;
  }
  window.location.href = '/settings';
};

const isFormData = (value: unknown): value is FormData => typeof FormData !== 'undefined' && value instanceof FormData;
const isUrlSearchParams = (value: unknown): value is URLSearchParams => value instanceof URLSearchParams;
const isBlob = (value: unknown): value is Blob => typeof Blob !== 'undefined' && value instanceof Blob;
const isArrayBuffer = (value: unknown): value is ArrayBuffer => typeof ArrayBuffer !== 'undefined' && value instanceof ArrayBuffer;
const isReadableStream = (value: unknown): value is ReadableStream =>
  typeof ReadableStream !== 'undefined' && value instanceof ReadableStream;

const prepareBody = (
  data: unknown,
  headers: Headers
): BodyInit | undefined => {
  if (data === undefined || data === null) {
    return undefined;
  }
  if (isFormData(data) || isUrlSearchParams(data) || isBlob(data) || isArrayBuffer(data)) {
    return data as BodyInit;
  }
  if (isReadableStream(data)) {
    return data as BodyInit;
  }
  if (typeof data === 'string') {
    if (!headers.has('Content-Type')) {
      headers.set('Content-Type', 'text/plain;charset=utf-8');
    }
    return data;
  }
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  return JSON.stringify(data);
};

const isApiErrorBody = (payload: unknown): payload is ApiErrorBody =>
  Boolean(
    payload &&
      typeof payload === 'object' &&
      typeof (payload as { code?: unknown }).code === 'string' &&
      typeof (payload as { message?: unknown }).message === 'string'
  );

const extractErrorBody = (payload: unknown): ApiErrorBody => {
  if (isApiErrorBody(payload)) {
    return payload;
  }
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>;
    const errorNode = record.error;
    if (isApiErrorBody(errorNode)) {
      return errorNode;
    }
    if (errorNode && typeof errorNode === 'object') {
      const code = typeof (errorNode as { code?: unknown }).code === 'string'
        ? (errorNode as { code: string }).code
        : typeof record.code === 'string'
          ? record.code
          : 'HTTP_ERROR';
      const message = typeof (errorNode as { message?: unknown }).message === 'string'
        ? (errorNode as { message: string }).message
        : typeof record.message === 'string'
          ? record.message
          : 'Request failed';
      const details = (errorNode as { details?: unknown }).details ?? record.details;
      return { code, message, details };
    }
    const code = typeof record.code === 'string' ? record.code : 'HTTP_ERROR';
    const message = typeof record.message === 'string'
      ? record.message
      : typeof record.detail === 'string'
        ? record.detail
        : typeof record.error === 'string'
          ? record.error
          : 'Request failed';
    const details = record.details;
    return { code, message, details };
  }
  if (typeof payload === 'string' && payload.trim().length > 0) {
    return { code: 'HTTP_ERROR', message: payload.trim() };
  }
  return { code: 'HTTP_ERROR', message: 'Request failed' };
};

  const parseErrorResponse = async (
    response: Response,
    fallback: string
  ): Promise<ApiErrorBody & { body?: unknown }> => {
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (contentType.includes('application/json')) {
    try {
      const json = await response.json();
      const body = extractErrorBody(json);
      return { ...body, body: json };
    } catch (error) {
      return { code: 'HTTP_ERROR', message: fallback, body: undefined };
    }
  }
  try {
    const text = await response.text();
    if (!text) {
      return { code: 'HTTP_ERROR', message: fallback, body: undefined };
    }
    try {
      const json = JSON.parse(text);
      const body = extractErrorBody(json);
      return { ...body, body: json };
    } catch (error) {
      return { code: 'HTTP_ERROR', message: text, body: text };
    }
  } catch (error) {
    return { code: 'HTTP_ERROR', message: fallback, body: undefined };
  }
};

const parseSuccessResponse = async <T>(response: Response, responseType: ResponseType): Promise<T> => {
  if (responseType === 'void') {
    return undefined as T;
  }
  if (responseType === 'blob') {
    return (await response.blob()) as T;
  }
  if (responseType === 'text') {
    return (await response.text()) as T;
  }
  if (response.status === 204 || response.status === 205) {
    return undefined as T;
  }
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (contentType.includes('application/json')) {
    try {
      return (await response.json()) as T;
    } catch (error) {
      return undefined as T;
    }
  }
  const text = await response.text();
  if (!text) {
    return undefined as T;
  }
  try {
    return JSON.parse(text) as T;
  } catch (error) {
    return text as unknown as T;
  }
};

const shouldRedirect = (status?: number) => status === 401 || status === 403;

export const request = async <T>(config: RequestConfig): Promise<T> => {
  if (USE_OPENAPI_CLIENT) {
    console.warn('OpenAPI client flag is enabled but no generated client is wired in this build. Falling back to fetch.');
  }

  const requestId = createRequestId();
  const method = (config.method ?? 'GET').toUpperCase();
  const url = buildUrl(config.url, config.params);
  const headers = new Headers();

  const appendHeaders = (source: HeadersInit | Record<string, string | undefined> | undefined) => {
    if (!source) {
      return;
    }
    if (source instanceof Headers) {
      source.forEach((value, key) => {
        if (value !== undefined) {
          headers.set(key, value);
        }
      });
      return;
    }
    if (Array.isArray(source)) {
      source.forEach(([key, value]) => {
        if (value !== undefined) {
          headers.set(key, value);
        }
      });
      return;
    }
    Object.entries(source).forEach(([key, value]) => {
      if (value !== undefined) {
        headers.set(key, value);
      }
    });
  };

  appendHeaders(config.headers);

  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }
  headers.set('X-Request-Id', requestId);

  const body = prepareBody(config.data, headers);

  if (REQUIRE_AUTH) {
    const key = resolveKey();
    if (!applyAuth(headers, key, getAuthMode())) {
      const error = new ApiError({
        code: AUTH_REQUIRED_PAYLOAD.error.code,
        message: AUTH_REQUIRED_PAYLOAD.error.message,
        status: 401,
        details: AUTH_REQUIRED_PAYLOAD,
        url: url.toString(),
        method,
        requestId
      });
      notifyApiError(error);
      redirectToSettings();
      throw error;
    }
  }

  const controller = new AbortController();
  if (config.signal) {
    if (config.signal.aborted) {
      controller.abort();
    } else {
      config.signal.addEventListener('abort', () => controller.abort(), { once: true });
    }
  }

  let timedOut = false;
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, API_TIMEOUT_MS);

  try {
    const response = await fetch(url.toString(), {
      method,
      headers,
      body,
      signal: controller.signal,
      credentials: config.credentials
    });

    const responseRequestId = response.headers.get('x-request-id') ?? requestId;

    if (!response.ok) {
      const fallbackMessage = response.statusText || 'Request failed';
      const errorBody = await parseErrorResponse(response, fallbackMessage);
      const error = new ApiError({
        code: errorBody.code,
        message: errorBody.message,
        status: response.status,
        details: errorBody.details,
        requestId: responseRequestId,
        url: url.toString(),
        method,
        body: errorBody.body
      });
      notifyApiError(error);
      if (shouldRedirect(error.status)) {
        redirectToSettings();
      }
      throw error;
    }

    return await parseSuccessResponse<T>(response, config.responseType ?? 'json');
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    const isAbortError =
      typeof DOMException !== 'undefined' && error instanceof DOMException
        ? error.name === 'AbortError'
        : error instanceof Error && error.name === 'AbortError';
    if (timedOut || isAbortError) {
      const timeoutError = new ApiError({
        code: 'TIMEOUT',
        message: 'Request timed out',
        status: 408,
        url: url.toString(),
        method,
        requestId,
        cause: error
      });
      notifyApiError(timeoutError);
      throw timeoutError;
    }
    const networkError = new ApiError({
      code: 'NETWORK_ERROR',
      message: error instanceof Error ? error.message : 'Network error',
      status: undefined,
      url: url.toString(),
      method,
      requestId,
      cause: error
    });
    notifyApiError(networkError);
    throw networkError;
  } finally {
    clearTimeout(timeoutId);
  }
};
