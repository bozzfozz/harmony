import { Navigate, Route, Routes } from 'react-router-dom';

import DashboardPage from '../pages/DashboardPage';
import LibraryPage from '../pages/Library';
import MatchingPage from '../pages/MatchingPage';
import SettingsPage from '../pages/SettingsPage';
import SoulseekPage from '../pages/SoulseekPage';
import SpotifyPage from '../pages/SpotifyPage';
import SpotifyProOAuthCallbackPage from '../pages/SpotifyProOAuthCallback';
import ArtistsPage from '../pages/Artists/ArtistsPage';
import ArtistDetailPage from '../pages/Artists/ArtistDetailPage';

const AppRoutes = () => (
  <Routes>
    <Route path="/" element={<Navigate to="/dashboard" replace />} />
    <Route path="/dashboard" element={<DashboardPage />} />
    <Route path="/library" element={<LibraryPage />} />
    <Route path="/downloads" element={<Navigate to="/library?tab=downloads" replace />} />
    <Route path="/artists" element={<ArtistsPage />} />
    <Route path="/artists/:id" element={<ArtistDetailPage />} />
    <Route path="/watchlist" element={<Navigate to="/artists" replace />} />
    <Route path="/spotify" element={<SpotifyPage />} />
    <Route path="/spotify/oauth/callback" element={<SpotifyProOAuthCallbackPage />} />
    <Route path="/soulseek" element={<SoulseekPage />} />
    <Route path="/matching" element={<MatchingPage />} />
    <Route path="/settings" element={<SettingsPage />} />
    <Route path="*" element={<Navigate to="/dashboard" replace />} />
  </Routes>
);

export default AppRoutes;
