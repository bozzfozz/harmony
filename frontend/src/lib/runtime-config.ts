declare global {
  interface Window {
    __HARMONY_API_URL__?: string;
    __HARMONY_API_BASE_PATH__?: string;
  }
}

const resolveApiBaseUrl = (): string => {
  const nodeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
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
  const nodeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
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

export const API_BASE_URL = resolveApiBaseUrl();
export const API_BASE_PATH = resolveApiBasePath();
