import { AxiosHeaders, type AxiosRequestConfig } from 'axios';

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
    localStorage.clear();
    delete window.__HARMONY_AUTH_HEADER_MODE__;
    delete window.__HARMONY_REQUIRE_AUTH__;
    delete window.__HARMONY_RUNTIME_API_KEY__;
  });

  afterEach(() => {
    resetEnv();
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
      const config: AxiosRequestConfig = {
        headers: AxiosHeaders.from({ Authorization: 'Bearer legacy' })
      };
      const applied = applyAuth(config, 'local-key', 'x-api-key');
      const headers = config.headers as AxiosHeaders;
      expect(applied).toBe(true);
      expect(headers.get('X-API-Key')).toBe('local-key');
      expect(headers.get('Authorization')).toBeUndefined();
    });
  });

  it('applies bearer token and removes X-API-Key header in bearer mode', async () => {
    await jest.isolateModulesAsync(async () => {
      const { applyAuth } = await import('../lib/auth');
      const config: AxiosRequestConfig = {
        headers: AxiosHeaders.from({ 'X-API-Key': 'legacy' })
      };
      const applied = applyAuth(config, 'bearer-key', 'bearer');
      const headers = config.headers as AxiosHeaders;
      expect(applied).toBe(true);
      expect(headers.get('Authorization')).toBe('Bearer bearer-key');
      expect(headers.get('X-API-Key')).toBeUndefined();
    });
  });

  it('sets Authorization header on outgoing requests when key is present', async () => {
    const env = ensureEnv();
    env.VITE_API_KEY = 'token-123';
    env.VITE_AUTH_HEADER_MODE = 'bearer';

    const calls: AxiosRequestConfig[] = [];

    await jest.isolateModulesAsync(async () => {
      const { api } = await import('../lib/api');
      api.defaults.adapter = async (config) => {
        calls.push(config);
        return {
          data: { ok: true },
          status: 200,
          statusText: 'OK',
          headers: new AxiosHeaders(),
          config
        };
      };

      await api.get('/protected');
    });

    expect(calls).toHaveLength(1);
    const requestConfig = calls[0];
    const headers = requestConfig.headers as AxiosHeaders;
    expect(headers.get('Authorization')).toBe('Bearer token-123');
    expect(headers.get('X-API-Key')).toBeUndefined();
  });

  it('blocks requests when auth is required but no key is available', async () => {
    ensureEnv().VITE_REQUIRE_AUTH = 'true';

    let adapterCalled = false;

    await jest.isolateModulesAsync(async () => {
      const { ApiError, api } = await import('../lib/api');
      api.defaults.adapter = async (config) => {
        adapterCalled = true;
        return {
          data: { ok: true },
          status: 200,
          statusText: 'OK',
          headers: new AxiosHeaders(),
          config
        };
      };

      await expect(api.get('/protected')).rejects.toBeInstanceOf(ApiError);
      await expect(api.get('/protected')).rejects.toMatchObject({
        message: 'API key missing',
        data: {
          ok: false,
          error: { code: 'AUTH_REQUIRED', message: 'API key missing' }
        }
      });
    });

    expect(adapterCalled).toBe(false);
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
