const ensureEnv = (): Record<string, string | undefined> => {
  const scope = globalThis as { process?: { env?: Record<string, string | undefined> } };
  if (!scope.process) {
    scope.process = { env: {} };
  }
  if (!scope.process.env) {
    scope.process.env = {};
  }
  return scope.process.env;
};

describe('auth header integration', () => {
  const originalEnv = { ...ensureEnv() };
  let originalFetch: typeof fetch | undefined;

  const resetEnv = () => {
    const env = ensureEnv();
    Object.keys(env).forEach((key) => {
      if (!(key in originalEnv)) {
        delete env[key];
      }
    });
    Object.assign(env, originalEnv);
  };

  beforeEach(() => {
    jest.resetModules();
    originalFetch = globalThis.fetch;
    (globalThis as typeof globalThis & { fetch: jest.Mock }).fetch = jest.fn();
    localStorage.clear();
    delete window.__HARMONY_AUTH_HEADER_MODE__;
    delete window.__HARMONY_REQUIRE_AUTH__;
    delete window.__HARMONY_RUNTIME_API_KEY__;
  });

  afterEach(() => {
    resetEnv();
    if (originalFetch) {
      (globalThis as typeof globalThis & { fetch: typeof fetch }).fetch = originalFetch;
    } else {
      delete (globalThis as Record<string, unknown>).fetch;
    }
  });

  it('prefers VITE_API_KEY over other sources when resolving the key', async () => {
    const env = ensureEnv();
    env.VITE_API_KEY = 'env-key';
    localStorage.setItem('HARMONY_API_KEY', 'stored-key');
    window.__HARMONY_RUNTIME_API_KEY__ = 'runtime-key';

    await jest.isolateModulesAsync(async () => {
      const { resolveKey } = await import('../lib/auth');
      expect(resolveKey()).toBe('env-key');
    });
  });

  it('uses localStorage key when environment variable is absent', async () => {
    localStorage.setItem('HARMONY_API_KEY', 'stored-key');
    window.__HARMONY_RUNTIME_API_KEY__ = 'runtime-key';

    await jest.isolateModulesAsync(async () => {
      const { resolveKey } = await import('../lib/auth');
      expect(resolveKey()).toBe('stored-key');
    });
  });

  it('falls back to runtime configuration when no other key exists', async () => {
    window.__HARMONY_RUNTIME_API_KEY__ = 'runtime-key';

    await jest.isolateModulesAsync(async () => {
      const { resolveKey } = await import('../lib/auth');
      expect(resolveKey()).toBe('runtime-key');
    });
  });

  it('applies X-API-Key header and removes bearer header in x-api-key mode', async () => {
    await jest.isolateModulesAsync(async () => {
      const { applyAuth } = await import('../lib/auth');
      const headers = new Headers({ Authorization: 'Bearer legacy' });
      const applied = applyAuth(headers, 'local-key', 'x-api-key');
      expect(applied).toBe(true);
      expect(headers.get('X-API-Key')).toBe('local-key');
      expect(headers.get('Authorization')).toBeNull();
    });
  });

  it('applies bearer token and removes X-API-Key header in bearer mode', async () => {
    await jest.isolateModulesAsync(async () => {
      const { applyAuth } = await import('../lib/auth');
      const headers = new Headers({ 'X-API-Key': 'legacy' });
      const applied = applyAuth(headers, 'bearer-key', 'bearer');
      expect(applied).toBe(true);
      expect(headers.get('Authorization')).toBe('Bearer bearer-key');
      expect(headers.get('X-API-Key')).toBeNull();
    });
  });

  it('sets Authorization header on outgoing requests when key is present', async () => {
    const env = ensureEnv();
    env.VITE_API_KEY = 'token-123';
    env.VITE_AUTH_HEADER_MODE = 'bearer';
    env.VITE_REQUIRE_AUTH = 'true';

    await jest.isolateModulesAsync(async () => {
      const fetchMock = (globalThis as typeof globalThis & { fetch: jest.Mock }).fetch;
      fetchMock.mockResolvedValue({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: new Headers(),
        json: jest.fn().mockResolvedValue({ ok: true }),
        text: jest.fn().mockResolvedValue(''),
        blob: jest.fn()
      });

      const { request } = await import('../api/client');
      await request({ url: '/protected', method: 'GET', responseType: 'json' });

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [, init] = fetchMock.mock.calls[0];
      const headers = (init as RequestInit).headers as Headers;
      expect(headers.get('Authorization')).toBe('Bearer token-123');
      expect(headers.get('X-API-Key')).toBeNull();
    });
  });

  it('omits auth headers when authentication is disabled', async () => {
    const env = ensureEnv();
    env.VITE_API_KEY = 'token-123';
    env.VITE_AUTH_HEADER_MODE = 'bearer';
    env.VITE_REQUIRE_AUTH = 'false';

    await jest.isolateModulesAsync(async () => {
      const fetchMock = (globalThis as typeof globalThis & { fetch: jest.Mock }).fetch;
      fetchMock.mockResolvedValue({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: new Headers(),
        json: jest.fn().mockResolvedValue({ ok: true }),
        text: jest.fn().mockResolvedValue(''),
        blob: jest.fn()
      });

      const { request } = await import('../api/client');
      await request({ url: '/protected', method: 'GET', responseType: 'json' });

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [, init] = fetchMock.mock.calls[0];
      const headers = (init as RequestInit).headers as Headers;
      expect(headers.get('Authorization')).toBeNull();
      expect(headers.get('X-API-Key')).toBeNull();
    });
  });

  it('blocks requests when auth is required but no key is available', async () => {
    ensureEnv().VITE_REQUIRE_AUTH = 'true';

    await jest.isolateModulesAsync(async () => {
      const fetchMock = (globalThis as typeof globalThis & { fetch: jest.Mock }).fetch;
      const { ApiError, request } = await import('../api/client');

      await expect(request({ url: '/protected', method: 'GET', responseType: 'json' })).rejects.toBeInstanceOf(ApiError);
      await expect(request({ url: '/protected', method: 'GET', responseType: 'json' })).rejects.toMatchObject({
        code: 'AUTH_REQUIRED',
        message: 'API key missing'
      });
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });
});

describe('AuthKeyPanel', () => {
  it('masks stored keys by default and reveals them on demand', async () => {
    await jest.isolateModulesAsync(async () => {
      const { getDisplayedKey, maskKey } = await import('../pages/Settings/AuthKeyPanel');
      expect(maskKey('secret')).toBe('••••••');
      expect(getDisplayedKey('super-secret', false)).toMatch(/^•+$/u);
      expect(getDisplayedKey('super-secret', true)).toBe('super-secret');
      expect(getDisplayedKey('   ', false)).toBe('Kein lokaler Key gespeichert.');
    });
  });
});
