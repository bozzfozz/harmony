import { AxiosHeaders, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios';

import { AUTH_HEADER_MODE, RUNTIME_API_KEY } from './runtime-config';

export type AuthHeaderMode = 'x-api-key' | 'bearer';

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
    // Zugriff auf localStorage kann in privaten Modi oder beim SSR fehlschlagen.
    return undefined;
  }
};

const ensureHeaders = (
  config: AxiosRequestConfig | InternalAxiosRequestConfig
): AxiosHeaders => {
  if (config.headers instanceof AxiosHeaders) {
    return config.headers;
  }
  const headers = AxiosHeaders.from((config.headers ?? {}) as Record<string, string>);
  config.headers = headers;
  return headers;
};

export const getAuthMode = (): AuthHeaderMode => AUTH_HEADER_MODE;

export const resolveKey = (): string | undefined =>
  resolveEnvKey() ?? resolveLocalStorageKey() ?? RUNTIME_API_KEY;

export const applyAuth = (
  config: AxiosRequestConfig | InternalAxiosRequestConfig,
  key: string | undefined,
  mode: AuthHeaderMode = getAuthMode()
): boolean => {
  const normalizedKey = normalizeKey(key);
  if (!normalizedKey) {
    return false;
  }
  const headers = ensureHeaders(config);
  if (mode === 'bearer') {
    headers.delete('X-API-Key');
    headers.set('Authorization', `Bearer ${normalizedKey}`);
  } else {
    headers.delete('Authorization');
    headers.set('X-API-Key', normalizedKey);
  }
  return true;
};
