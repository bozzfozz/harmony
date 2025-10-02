interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_API_URL?: string;
  readonly VITE_API_BASE_PATH?: string;
  readonly VITE_API_TIMEOUT_MS?: string;
  readonly VITE_REQUIRE_AUTH?: string;
  readonly VITE_AUTH_HEADER_MODE?: string;
  readonly VITE_USE_OPENAPI_CLIENT?: string;
  readonly VITE_LIBRARY_POLL_INTERVAL_MS?: string;
  readonly VITE_RUNTIME_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
