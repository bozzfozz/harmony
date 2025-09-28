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
  }
}

if (typeof window !== 'undefined') {
  window.__HARMONY_API_URL__ = import.meta.env?.VITE_API_URL;
  window.__HARMONY_API_BASE_PATH__ = import.meta.env?.VITE_API_BASE_PATH;
  window.__HARMONY_LIBRARY_POLL_INTERVAL_MS__ = import.meta.env?.VITE_LIBRARY_POLL_INTERVAL_MS;
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
