declare global {
  interface Window {
    __HARMONY_API_URL__?: string;
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

export const API_BASE_URL = resolveApiBaseUrl();
