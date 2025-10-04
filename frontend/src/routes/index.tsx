import { Navigate, Route, Routes } from 'react-router-dom';

import DashboardPage from '../pages/DashboardPage';
import LibraryPage from '../pages/Library';
import MatchingPage from '../pages/MatchingPage';
import SettingsPage from '../pages/SettingsPage';
import SoulseekPage from '../pages/SoulseekPage';
import SpotifyPage from '../pages/SpotifyPage';

const AppRoutes = () => (
  <Routes>
    <Route path="/" element={<Navigate to="/dashboard" replace />} />
    <Route path="/dashboard" element={<DashboardPage />} />
    <Route path="/library" element={<LibraryPage />} />
    <Route path="/downloads" element={<Navigate to="/library?tab=downloads" replace />} />
    <Route path="/artists" element={<Navigate to="/library?tab=artists" replace />} />
    <Route path="/watchlist" element={<Navigate to="/library?tab=watchlist" replace />} />
    <Route path="/spotify" element={<SpotifyPage />} />
    <Route path="/soulseek" element={<SoulseekPage />} />
    <Route path="/matching" element={<MatchingPage />} />
    <Route path="/settings" element={<SettingsPage />} />
    <Route path="*" element={<Navigate to="/dashboard" replace />} />
  </Routes>
);

export default AppRoutes;
