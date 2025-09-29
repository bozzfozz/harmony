declare global {
  interface Window {
    __HARMONY_API_URL__?: string;
    __HARMONY_API_BASE_PATH__?: string;
    __HARMONY_LIBRARY_POLL_INTERVAL_MS__?: string;
    __HARMONY_REQUIRE_AUTH__?: string | boolean;
    __HARMONY_AUTH_HEADER_MODE__?: string;
    __HARMONY_RUNTIME_API_KEY__?: string;
  }
}

const getNodeEnv = () => (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;

const resolveApiBaseUrl = (): string => {
  const nodeEnv = getNodeEnv();
  if (nodeEnv?.VITE_API_URL) {
    return nodeEnv.VITE_API_URL;
  }

  if (typeof window !== 'undefined' && typeof window.__HARMONY_API_URL__ === 'string') {
    return window.__HARMONY_API_URL__;
  }

  return 'http://localhost:8000';
};

const normalizeBasePath = (value: string): string => {
  const trimmed = value.trim();
  if (!trimmed || trimmed === '/') {
    return '';
  }
  const withLeadingSlash = trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
  return withLeadingSlash.replace(/\/+$/u, '');
};

const resolveApiBasePath = (): string => {
  const nodeEnv = getNodeEnv();
  if (nodeEnv?.VITE_API_BASE_PATH) {
    return normalizeBasePath(nodeEnv.VITE_API_BASE_PATH);
  }

  if (
    typeof window !== 'undefined' &&
    typeof window.__HARMONY_API_BASE_PATH__ === 'string'
  ) {
    return normalizeBasePath(window.__HARMONY_API_BASE_PATH__);
  }

  return normalizeBasePath('/api/v1');
};

const parseBoolean = (value: unknown): boolean | undefined => {
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (['1', 'true', 'yes', 'on'].includes(normalized)) {
      return true;
    }
    if (['0', 'false', 'no', 'off'].includes(normalized)) {
      return false;
    }
  }
  return undefined;
};

const resolveRequireAuth = (): boolean => {
  const nodeEnv = getNodeEnv();
  const envValue = parseBoolean(nodeEnv?.VITE_REQUIRE_AUTH);
  if (envValue !== undefined) {
    return envValue;
  }

  if (typeof window !== 'undefined') {
    const browserValue = parseBoolean(window.__HARMONY_REQUIRE_AUTH__);
    if (browserValue !== undefined) {
      return browserValue;
    }
  }

  return true;
};

type AuthHeaderMode = 'x-api-key' | 'bearer';

const normalizeAuthMode = (value: unknown): AuthHeaderMode | undefined => {
  if (typeof value !== 'string') {
    return undefined;
  }
  const normalized = value.trim().toLowerCase();
  if (normalized === 'bearer') {
    return 'bearer';
  }
  if (normalized === 'x-api-key' || normalized === 'x_api_key' || normalized === 'xapikey') {
    return 'x-api-key';
  }
  return undefined;
};

const resolveAuthHeaderMode = (): AuthHeaderMode => {
  const nodeEnv = getNodeEnv();
  const envValue = normalizeAuthMode(nodeEnv?.VITE_AUTH_HEADER_MODE);
  if (envValue) {
    return envValue;
  }

  if (typeof window !== 'undefined') {
    const browserValue = normalizeAuthMode(window.__HARMONY_AUTH_HEADER_MODE__);
    if (browserValue) {
      return browserValue;
    }
  }

  return 'x-api-key';
};

const resolveRuntimeApiKey = (): string | undefined => {
  if (typeof window === 'undefined') {
    return undefined;
  }
  const value = window.__HARMONY_RUNTIME_API_KEY__;
  if (typeof value !== 'string') {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

export const API_BASE_URL = resolveApiBaseUrl();
export const API_BASE_PATH = resolveApiBasePath();
export const REQUIRE_AUTH = resolveRequireAuth();
export const AUTH_HEADER_MODE: AuthHeaderMode = resolveAuthHeaderMode();
export const RUNTIME_API_KEY = resolveRuntimeApiKey();
