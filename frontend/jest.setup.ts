import './src/testing/jest-matchers';
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
