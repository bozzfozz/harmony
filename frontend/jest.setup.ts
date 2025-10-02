import '@testing-library/jest-dom';

const globalProcess = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
if (globalProcess) {
  globalProcess.env = {
    ...globalProcess.env,
    VITE_API_BASE_URL: globalProcess.env?.VITE_API_BASE_URL ?? globalProcess.env?.VITE_API_URL ?? 'http://127.0.0.1:8000',
    VITE_API_URL: globalProcess.env?.VITE_API_URL ?? 'http://127.0.0.1:8000',
    VITE_API_BASE_PATH: globalProcess.env?.VITE_API_BASE_PATH ?? '',
    VITE_API_TIMEOUT_MS: globalProcess.env?.VITE_API_TIMEOUT_MS ?? '8000'
  };
}

const importMetaEnv = {
  VITE_API_BASE_URL: globalProcess?.env?.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000',
  VITE_API_BASE_PATH: globalProcess?.env?.VITE_API_BASE_PATH ?? '',
  VITE_API_TIMEOUT_MS: globalProcess?.env?.VITE_API_TIMEOUT_MS ?? '8000',
  VITE_REQUIRE_AUTH: globalProcess?.env?.VITE_REQUIRE_AUTH,
  VITE_AUTH_HEADER_MODE: globalProcess?.env?.VITE_AUTH_HEADER_MODE,
  VITE_USE_OPENAPI_CLIENT: globalProcess?.env?.VITE_USE_OPENAPI_CLIENT,
  VITE_LIBRARY_POLL_INTERVAL_MS: globalProcess?.env?.VITE_LIBRARY_POLL_INTERVAL_MS
};

(globalThis as typeof globalThis & { __HARMONY_IMPORT_META_ENV__?: Record<string, unknown> }).__HARMONY_IMPORT_META_ENV__ = {
  ...(globalThis as typeof globalThis & { __HARMONY_IMPORT_META_ENV__?: Record<string, unknown> }).__HARMONY_IMPORT_META_ENV__,
  ...importMetaEnv
};
