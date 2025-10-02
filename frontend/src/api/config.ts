const getNodeEnv = () => (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;

type ImportMetaEnvLike = Record<string, unknown> | undefined;

const getImportMetaEnv = (): ImportMetaEnvLike => {
  if (typeof window !== 'undefined') {
    return (window as typeof window & { __HARMONY_IMPORT_META_ENV__?: Record<string, unknown> }).__HARMONY_IMPORT_META_ENV__;
  }

  return (globalThis as typeof globalThis & { __HARMONY_IMPORT_META_ENV__?: Record<string, unknown> }).__HARMONY_IMPORT_META_ENV__;
};

const importMetaEnv = getImportMetaEnv();

const normalizeString = (value: unknown): string | undefined => {
  if (typeof value !== 'string') {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

const parseBoolean = (value: unknown): boolean | undefined => {
  if (typeof value === 'boolean') {
    return value;
  }
  const normalized = normalizeString(value)?.toLowerCase();
  if (!normalized) {
    return undefined;
  }
  if (['1', 'true', 'yes', 'on'].includes(normalized)) {
    return true;
  }
  if (['0', 'false', 'no', 'off'].includes(normalized)) {
    return false;
  }
  return undefined;
};

const parseNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : undefined;
  }
  if (typeof value === 'string') {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

export type AuthHeaderMode = 'x-api-key' | 'bearer';

const normalizeAuthMode = (value: unknown): AuthHeaderMode | undefined => {
  if (typeof value !== 'string') {
    return undefined;
  }
  const normalized = value.trim().toLowerCase();
  if (normalized === 'bearer') {
    return 'bearer';
  }
  if (['x-api-key', 'x_api_key', 'xapikey'].includes(normalized)) {
    return 'x-api-key';
  }
  return undefined;
};

const normalizeBasePath = (value: string): string => {
  const trimmed = value.trim();
  if (!trimmed || trimmed === '/') {
    return '';
  }
  const withLeadingSlash = trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
  return withLeadingSlash.replace(/\/+$/u, '');
};

const resolveBaseUrl = (): string => {
  const env = getNodeEnv();
  const envValue = normalizeString(env?.VITE_API_BASE_URL ?? env?.VITE_API_URL);
  if (envValue) {
    return envValue;
  }
  if (typeof window !== 'undefined') {
    const browserValue = normalizeString((window as typeof window & { __HARMONY_API_URL__?: string }).__HARMONY_API_URL__);
    if (browserValue) {
      return browserValue;
    }
  }
  return 'http://127.0.0.1:8000';
};

const resolveBasePath = (): string => {
  const env = getNodeEnv();
  const envValue = normalizeString(env?.VITE_API_BASE_PATH);
  if (envValue) {
    return normalizeBasePath(envValue);
  }
  if (typeof window !== 'undefined') {
    const browserValue = normalizeString(
      (window as typeof window & { __HARMONY_API_BASE_PATH__?: string }).__HARMONY_API_BASE_PATH__
    );
    if (browserValue) {
      return normalizeBasePath(browserValue);
    }
  }
  return '';
};

const resolveTimeout = (): number =>
  parseNumber(importMetaEnv?.VITE_API_TIMEOUT_MS) ?? parseNumber(getNodeEnv()?.VITE_API_TIMEOUT_MS) ?? 8000;

const resolveRequireAuth = (): boolean => {
  const env = getNodeEnv();
  const envValue = parseBoolean(importMetaEnv?.VITE_REQUIRE_AUTH ?? env?.VITE_REQUIRE_AUTH);
  if (envValue !== undefined) {
    return envValue;
  }
  if (typeof window !== 'undefined') {
    const browserValue = parseBoolean(
      (window as typeof window & { __HARMONY_REQUIRE_AUTH__?: string | boolean }).__HARMONY_REQUIRE_AUTH__
    );
    if (browserValue !== undefined) {
      return browserValue;
    }
  }
  return false;
};

const resolveAuthMode = (): AuthHeaderMode => {
  const env = getNodeEnv();
  return (
    normalizeAuthMode(importMetaEnv?.VITE_AUTH_HEADER_MODE ?? env?.VITE_AUTH_HEADER_MODE) ??
    normalizeAuthMode(
      typeof window !== 'undefined'
        ? (window as typeof window & { __HARMONY_AUTH_HEADER_MODE__?: string }).__HARMONY_AUTH_HEADER_MODE__
        : undefined
    ) ??
    'x-api-key'
  );
};

const resolveRuntimeKey = (): string | undefined => {
  if (typeof window === 'undefined') {
    return undefined;
  }
  const runtimeKey = (window as typeof window & { __HARMONY_RUNTIME_API_KEY__?: string }).__HARMONY_RUNTIME_API_KEY__;
  return normalizeString(runtimeKey);
};

const resolveLibraryPollInterval = (): number => {
  const env = getNodeEnv();
  const sources = [
    importMetaEnv?.VITE_LIBRARY_POLL_INTERVAL_MS,
    env?.VITE_LIBRARY_POLL_INTERVAL_MS,
    typeof window !== 'undefined'
      ? (window as typeof window & { __HARMONY_LIBRARY_POLL_INTERVAL_MS__?: string }).__HARMONY_LIBRARY_POLL_INTERVAL_MS__
      : undefined
  ];
  for (const value of sources) {
    const parsed = parseNumber(value);
    if (parsed !== undefined && parsed > 0) {
      return parsed;
    }
  }
  return 15000;
};

const resolveOpenApiFlag = (): boolean =>
  parseBoolean(importMetaEnv?.VITE_USE_OPENAPI_CLIENT ?? getNodeEnv()?.VITE_USE_OPENAPI_CLIENT) ?? false;

export const API_BASE_URL = resolveBaseUrl();
export const API_BASE_PATH = resolveBasePath();
export const API_TIMEOUT_MS = resolveTimeout();
export const REQUIRE_AUTH = resolveRequireAuth();
export const AUTH_HEADER_MODE = resolveAuthMode();
export const RUNTIME_API_KEY = resolveRuntimeKey();
export const LIBRARY_POLL_INTERVAL_MS = resolveLibraryPollInterval();
export const USE_OPENAPI_CLIENT = resolveOpenApiFlag();

export const buildAbsoluteUrl = (path: string): string => {
  if (/^https?:/iu.test(path)) {
    return path;
  }
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const base = API_BASE_URL.replace(/\/+$/u, '');
  const basePath = API_BASE_PATH ? API_BASE_PATH.replace(/\/+$/u, '') : '';
  return `${base}${basePath}${normalizedPath}` || '/';
};
