import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";

import Layout from "./components/Layout";
import DashboardPage from "./pages/DashboardPage";
import SpotifyPage from "./pages/SpotifyPage";
import PlexPage from "./pages/PlexPage";
import SoulseekPage from "./pages/SoulseekPage";
import BeetsPage from "./pages/BeetsPage";
import Matching from "./pages/Matching";
import Settings from "./pages/Settings";
import { Toaster } from "./components/ui/toaster";
import AppHeader, { ServiceFilters } from "./components/AppHeader";
import { useToast } from "./components/ui/use-toast";
import useTheme from "./hooks/useTheme";
import { SearchProvider } from "./hooks/useGlobalSearch";

const defaultFilters: ServiceFilters = {
  spotify: true,
  plex: true,
  soulseek: true
};

const AppRoutes = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [filters, setFilters] = useState<ServiceFilters>(defaultFilters);
  const [searchTerm, setSearchTerm] = useState("");
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [hasNewFeatures, setHasNewFeatures] = useState(true);
  const { theme, toggleTheme } = useTheme();
  const [loading, setLoading] = useState(false);
  const refreshTimerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    return () => {
      if (refreshTimerRef.current !== undefined) {
        window.clearTimeout(refreshTimerRef.current);
      }
    };
  }, []);

  const header = useMemo(
    () => (
      <AppHeader
        loading={loading}
        onRefresh={() => {
          if (refreshTimerRef.current) {
            window.clearTimeout(refreshTimerRef.current);
          }
          setLoading(true);
          refreshTimerRef.current = window.setTimeout(() => {
            setLoading(false);
          }, 800);
        }}
        searchTerm={searchTerm}
        onSearchChange={setSearchTerm}
        filters={filters}
        onFilterChange={setFilters}
        isDarkMode={theme === "dark"}
        onThemeToggle={toggleTheme}
        onGoHome={() => navigate("/dashboard")}
        onToggleSidebar={() => setIsSidebarOpen((open) => !open)}
        onShowWhatsNew={() => {
          toast({
            title: "Harmony Update",
            description: "Die neuesten Änderungen wurden geladen."
          });
          setHasNewFeatures(false);
        }}
        onShowNotifications={() => {
          toast({
            title: "Benachrichtigungen",
            description: "Keine neuen Benachrichtigungen"
          });
        }}
        hasNewFeatures={hasNewFeatures}
      />
    ),
    [
      filters,
      hasNewFeatures,
      loading,
      navigate,
      searchTerm,
      setFilters,
      setHasNewFeatures,
      setIsSidebarOpen,
      setSearchTerm,
      theme,
      toggleTheme,
      toast
    ]
  );

  return (
    <>
      <Toaster />
      <SearchProvider value={{ term: searchTerm, setTerm: setSearchTerm }}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route
            element={
              <Layout
                header={header}
                isSidebarOpen={isSidebarOpen}
                onSidebarOpenChange={setIsSidebarOpen}
              />
            }
          >
            <Route path="/dashboard" element={<DashboardPage filters={filters} />} />
            <Route path="/spotify" element={<SpotifyPage filters={filters} />} />
            <Route path="/plex" element={<PlexPage filters={filters} />} />
            <Route path="/soulseek" element={<SoulseekPage filters={filters} />} />
            <Route path="/beets" element={<BeetsPage />} />
            <Route path="/matching" element={<Matching />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </SearchProvider>
    </>
  );
};

function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}

export default App;
