import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import SpotifyPage from './pages/SpotifyPage';
import PlexPage from './pages/PlexPage';
import SoulseekPage from './pages/SoulseekPage';
import MatchingPage from './pages/MatchingPage';
import SettingsPage from './pages/SettingsPage';
import BeetsPage from './pages/BeetsPage';
import DownloadsPage from './pages/DownloadsPage';
import { ThemeProvider } from './components/theme-provider';
import ToastProvider from './components/ToastProvider';
import ArtistsPage from './pages/ArtistsPage';

const App = () => (
  <ThemeProvider>
    <ToastProvider>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/spotify" element={<SpotifyPage />} />
          <Route path="/artists" element={<ArtistsPage />} />
          <Route path="/plex" element={<PlexPage />} />
          <Route path="/soulseek" element={<SoulseekPage />} />
          <Route path="/downloads" element={<DownloadsPage />} />
          <Route path="/beets" element={<BeetsPage />} />
          <Route path="/matching" element={<MatchingPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </Layout>
    </ToastProvider>
  </ThemeProvider>
);

export default App;
