import '@testing-library/jest-dom';

const globalProcess = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
if (globalProcess) {
  globalProcess.env = {
    ...globalProcess.env,
    VITE_API_URL: globalProcess.env?.VITE_API_URL ?? 'http://localhost:8000'
  };
}
