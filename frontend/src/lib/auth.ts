import type { AuthHeaderMode } from '../api/config';
import { AUTH_HEADER_MODE, RUNTIME_API_KEY } from '../api/config';

export { AUTH_HEADER_MODE } from '../api/config';

export const LOCAL_STORAGE_KEY = 'HARMONY_API_KEY';

const getNodeEnv = () => (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;

const normalizeKey = (value: unknown): string | undefined => {
  if (typeof value !== 'string') {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

const resolveEnvKey = (): string | undefined => normalizeKey(getNodeEnv()?.VITE_API_KEY);

const resolveLocalStorageKey = (): string | undefined => {
  if (typeof window === 'undefined') {
    return undefined;
  }
  try {
    return normalizeKey(window.localStorage.getItem(LOCAL_STORAGE_KEY));
  } catch (error) {
    return undefined;
  }
};

export const getAuthMode = (): AuthHeaderMode => AUTH_HEADER_MODE;

export const resolveKey = (): string | undefined =>
  resolveEnvKey() ?? resolveLocalStorageKey() ?? RUNTIME_API_KEY;

type MutableHeaders = Headers | Record<string, string | undefined>;

const setHeader = (headers: MutableHeaders, key: string, value: string | undefined) => {
  if (headers instanceof Headers) {
    if (value === undefined) {
      headers.delete(key);
    } else {
      headers.set(key, value);
    }
    return;
  }
  if (value === undefined) {
    delete headers[key];
  } else {
    headers[key] = value;
  }
};

export const applyAuth = (
  headers: MutableHeaders,
  key: string | undefined,
  mode: AuthHeaderMode = getAuthMode()
): boolean => {
  const normalizedKey = normalizeKey(key);
  if (!normalizedKey) {
    setHeader(headers, 'Authorization', undefined);
    setHeader(headers, 'X-API-Key', undefined);
    return false;
  }

  if (mode === 'bearer') {
    setHeader(headers, 'Authorization', `Bearer ${normalizedKey}`);
    setHeader(headers, 'X-API-Key', undefined);
  } else {
    setHeader(headers, 'X-API-Key', normalizedKey);
    setHeader(headers, 'Authorization', undefined);
  }
  return true;
};
