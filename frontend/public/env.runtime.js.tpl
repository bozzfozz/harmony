(function () {
  const runtimeConfig = {
    backendUrl: "${PUBLIC_BACKEND_URL}",
    sentryDsn: "${PUBLIC_SENTRY_DSN}",
    featureFlags: ${PUBLIC_FEATURE_FLAGS}
  };

  window.__HARMONY_RUNTIME_CONFIG__ = runtimeConfig;

  if (typeof runtimeConfig.backendUrl === 'string' && runtimeConfig.backendUrl.trim().length > 0) {
    window.__HARMONY_API_URL__ = runtimeConfig.backendUrl;
  }

  if (typeof runtimeConfig.sentryDsn === 'string' && runtimeConfig.sentryDsn.trim().length > 0) {
    window.__HARMONY_RUNTIME_SENTRY_DSN__ = runtimeConfig.sentryDsn;
  }

  if (runtimeConfig.featureFlags && typeof runtimeConfig.featureFlags === 'object') {
    window.__HARMONY_RUNTIME_FEATURE_FLAGS__ = runtimeConfig.featureFlags;
  }
})();
