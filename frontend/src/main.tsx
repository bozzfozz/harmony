import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles/index.css';
import { QueryClient, QueryClientProvider } from './lib/query';

declare global {
  interface Window {
    __HARMONY_API_URL__?: string;
    __HARMONY_API_BASE_PATH__?: string;
    __HARMONY_LIBRARY_POLL_INTERVAL_MS__?: string;
    __HARMONY_REQUIRE_AUTH__?: string | boolean;
    __HARMONY_AUTH_HEADER_MODE__?: string;
    __HARMONY_RUNTIME_API_KEY__?: string;
    __HARMONY_IMPORT_META_ENV__?: ImportMetaEnv;
    __HARMONY_RUNTIME_CONFIG__?: {
      backendUrl?: string | null;
      sentryDsn?: string | null;
      featureFlags?: Record<string, unknown> | null;
    };
    __HARMONY_RUNTIME_FEATURE_FLAGS__?: Record<string, unknown>;
    __HARMONY_RUNTIME_SENTRY_DSN__?: string;
  }
}

if (typeof window !== 'undefined') {
  const runtimeConfig = window.__HARMONY_RUNTIME_CONFIG__;
  window.__HARMONY_IMPORT_META_ENV__ = import.meta.env;
  const runtimeBackendUrl =
    typeof runtimeConfig?.backendUrl === 'string' && runtimeConfig.backendUrl.trim().length > 0
      ? runtimeConfig.backendUrl
      : undefined;
  window.__HARMONY_API_URL__ = runtimeBackendUrl ?? import.meta.env?.VITE_API_BASE_URL ?? import.meta.env?.VITE_API_URL;
  window.__HARMONY_API_BASE_PATH__ = import.meta.env?.VITE_API_BASE_PATH;
  window.__HARMONY_LIBRARY_POLL_INTERVAL_MS__ = import.meta.env?.VITE_LIBRARY_POLL_INTERVAL_MS;
  window.__HARMONY_REQUIRE_AUTH__ = import.meta.env?.VITE_REQUIRE_AUTH;
  window.__HARMONY_AUTH_HEADER_MODE__ = import.meta.env?.VITE_AUTH_HEADER_MODE;
  window.__HARMONY_RUNTIME_API_KEY__ = import.meta.env?.VITE_RUNTIME_API_KEY;
  const featureFlags = runtimeConfig?.featureFlags;
  if (featureFlags && typeof featureFlags === 'object') {
    window.__HARMONY_RUNTIME_FEATURE_FLAGS__ = featureFlags;
  } else if (!window.__HARMONY_RUNTIME_FEATURE_FLAGS__) {
    window.__HARMONY_RUNTIME_FEATURE_FLAGS__ = {};
  }
  if (typeof runtimeConfig?.sentryDsn === 'string' && runtimeConfig.sentryDsn.trim().length > 0) {
    window.__HARMONY_RUNTIME_SENTRY_DSN__ = runtimeConfig.sentryDsn;
  }
}

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
