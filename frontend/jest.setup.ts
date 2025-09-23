import '@testing-library/jest-dom';
import { server, resetSettings } from './tests/server';

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
});

afterEach(() => {
  server.resetHandlers();
  resetSettings();
});

afterAll(() => {
  server.close();
});
