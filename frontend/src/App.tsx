import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import ApiErrorListener from './components/ApiErrorListener';
import Toaster from './components/ui/toaster';
import { ThemeProvider } from './components/theme-provider';
import DashboardPage from './pages/DashboardPage';
import DownloadsPage from './pages/DownloadsPage';
import ArtistsPage from './pages/ArtistsPage';
import SettingsPage from './pages/SettingsPage';

const App = () => (
  <ThemeProvider>
    <ApiErrorListener />
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/downloads" element={<DownloadsPage />} />
        <Route path="/artists" element={<ArtistsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Layout>
    <Toaster />
  </ThemeProvider>
);

export default App;
