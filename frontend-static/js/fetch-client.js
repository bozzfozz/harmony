const RETRYABLE_STATUSES = new Set([408, 425, 429, 500, 502, 503, 504]);

function shouldRetryStatus(status) {
  return RETRYABLE_STATUSES.has(status) || (status >= 500 && status < 600);
}

function createDelay(ms, signal) {
  if (ms <= 0) {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(() => {
      if (signal) {
        signal.removeEventListener('abort', onAbort);
      }
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'));
    };
    if (signal) {
      signal.addEventListener('abort', onAbort, { once: true });
    }
  });
}

export class FetchError extends Error {
  constructor(message, { status, statusText, url, data, attempt, cause } = {}) {
    super(message);
    this.name = 'FetchError';
    this.status = status ?? null;
    this.statusText = statusText ?? '';
    this.url = url ?? '';
    this.data = data ?? null;
    this.attempt = attempt ?? null;
    if (cause) {
      this.cause = cause;
    }
  }
}

function mergeSignals(controller, externalSignal) {
  if (!externalSignal) {
    return;
  }
  if (externalSignal.aborted) {
    controller.abort(externalSignal.reason);
    return;
  }
  const onAbort = () => {
    controller.abort(externalSignal.reason);
  };
  externalSignal.addEventListener('abort', onAbort, { once: true });
}

async function parseBody(response) {
  const contentType = response.headers.get('content-type') || '';
  const text = await response.text();
  if (!text) {
    return null;
  }
  if (contentType.includes('application/json') || contentType.includes('+json')) {
    try {
      return JSON.parse(text);
    } catch (error) {
      return { raw: text, error: 'invalid_json' };
    }
  }
  return text;
}

function computeDelay(baseDelay, factor, attempt, jitter) {
  const delay = Math.min(baseDelay * factor ** (attempt - 1), 10000);
  if (!jitter) {
    return delay;
  }
  const spread = delay * jitter;
  const random = Math.random() * spread - spread / 2;
  return Math.max(0, Math.round(delay + random));
}

export function fetchWithRetry(input, init = {}) {
  const {
    retry,
    timeoutMs = 0,
    signal: externalSignal,
    headers,
    ...rest
  } = init;
  const {
    attempts = 3,
    baseDelay = 250,
    backoffFactor = 2,
    jitter = 0.25,
  } = retry ?? {};

  const controller = new AbortController();
  mergeSignals(controller, externalSignal);
  const fetchInit = {
    ...rest,
    headers,
    signal: controller.signal,
  };

  let timeoutId = null;
  if (timeoutMs > 0) {
    timeoutId = setTimeout(() => {
      controller.abort(new DOMException('Timed out', 'TimeoutError'));
    }, timeoutMs);
  }

  const promise = (async () => {
    let lastError = null;
    for (let attempt = 1; attempt <= Math.max(1, attempts); attempt += 1) {
      if (controller.signal.aborted) {
        throw controller.signal.reason ?? new DOMException('Aborted', 'AbortError');
      }
      try {
        const response = await fetch(input, fetchInit);
        if (!response.ok) {
          const body = await parseBody(response.clone());
          const error = new FetchError(
            `Request failed with status ${response.status}`,
            {
              status: response.status,
              statusText: response.statusText,
              url: typeof input === 'string' ? input : input.url,
              data: body,
              attempt,
            },
          );
          if (attempt < attempts && shouldRetryStatus(response.status)) {
            lastError = error;
            const delay = computeDelay(baseDelay, backoffFactor, attempt, jitter);
            await createDelay(delay, controller.signal);
            continue;
          }
          throw error;
        }
        return response;
      } catch (error) {
        if (controller.signal.aborted) {
          throw controller.signal.reason ?? error;
        }
        if (error instanceof FetchError) {
          if (attempt >= attempts) {
            throw error;
          }
          lastError = error;
          const delay = computeDelay(baseDelay, backoffFactor, attempt, jitter);
          await createDelay(delay, controller.signal);
          continue;
        }
        if (error?.name === 'AbortError') {
          throw error;
        }
        if (attempt >= attempts) {
          throw new FetchError('Network request failed', {
            url: typeof input === 'string' ? input : input.url,
            attempt,
            cause: error,
          });
        }
        lastError = error;
        const delay = computeDelay(baseDelay, backoffFactor, attempt, jitter);
        await createDelay(delay, controller.signal);
      }
    }
    throw lastError ?? new FetchError('Request failed');
  })().finally(() => {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
  });

  return {
    promise,
    abort: () => controller.abort(),
  };
}

export function fetchJson(input, init = {}) {
  const { promise, abort } = fetchWithRetry(input, init);
  return {
    abort,
    promise: promise.then(async (response) => {
      const contentType = response.headers.get('content-type') || '';
      if (
        response.status === 204 ||
        (!contentType.includes('json') && !contentType.includes('+json'))
      ) {
        if (response.status === 204) {
          return null;
        }
        const text = await response.text();
        if (!text) {
          return null;
        }
        try {
          return JSON.parse(text);
        } catch (error) {
          return text;
        }
      }
      return response.json();
    }),
  };
}

export function isAbortError(error) {
  return error?.name === 'AbortError' || error instanceof DOMException;
}
