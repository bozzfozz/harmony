import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles/index.css';
import { QueryClient, QueryClientProvider } from './lib/query';

declare global {
  interface Window {
    __HARMONY_API_URL__?: string;
  }
}

if (typeof window !== 'undefined') {
  window.__HARMONY_API_URL__ = import.meta.env?.VITE_API_URL;
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
