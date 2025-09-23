import { useEffect, useMemo, useState } from "react";
import { RefreshCw, Loader2, Search, X, Sun, Moon, Menu, Sparkles, Bell } from "lucide-react";

import { Button } from "./ui/button";
import { Input } from "./ui/input";
import Logo from "./Logo";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger
} from "./ui/tooltip";

type ServiceFilters = {
  spotify: boolean;
  plex: boolean;
  soulseek: boolean;
};

interface AppHeaderProps {
  loading: boolean;
  onRefresh: () => void;
  searchTerm: string;
  onSearchChange: (value: string) => void;
  filters: ServiceFilters;
  onFilterChange: (filters: ServiceFilters) => void;
  isDarkMode: boolean;
  onThemeToggle: () => void;
  onGoHome: () => void;
  onToggleSidebar: () => void;
  onShowWhatsNew?: () => void;
  onShowNotifications?: () => void;
  hasNewFeatures?: boolean;
}

const SEARCH_DEBOUNCE = 300;

const AppHeader = ({
  loading,
  onRefresh,
  searchTerm,
  onSearchChange,
  filters,
  onFilterChange,
  isDarkMode,
  onThemeToggle,
  onGoHome,
  onToggleSidebar,
  onShowWhatsNew,
  onShowNotifications,
  hasNewFeatures = false
}: AppHeaderProps) => {
  const [localSearchTerm, setLocalSearchTerm] = useState(searchTerm);
  const [searching, setSearching] = useState(false);

  const filterButtons = useMemo(
    () => [
      {
        key: "spotify" as const,
        label: "Spotify",
        isActive: filters.spotify,
        activeClass:
          "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
        onClick: () =>
          onFilterChange({ ...filters, spotify: !filters.spotify }),
        title: filters.spotify
          ? "Disable Spotify filter"
          : "Enable Spotify filter"
      },
      {
        key: "plex" as const,
        label: "Plex",
        isActive: filters.plex,
        activeClass:
          "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
        onClick: () => onFilterChange({ ...filters, plex: !filters.plex }),
        title: filters.plex ? "Disable Plex filter" : "Enable Plex filter"
      },
      {
        key: "soulseek" as const,
        label: "Soulseek",
        isActive: filters.soulseek,
        activeClass:
          "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
        onClick: () =>
          onFilterChange({ ...filters, soulseek: !filters.soulseek }),
        title: filters.soulseek
          ? "Disable Soulseek filter"
          : "Enable Soulseek filter"
      }
    ],
    [filters, onFilterChange]
  );

  const searchIcon = useMemo(
    () =>
      searching ? (
        <Loader2 className="h-4 w-4 text-indigo-500 animate-spin" />
      ) : (
        <Search className="h-4 w-4 text-gray-400" />
      ),
    [searching]
  );

  const refreshIcon = useMemo(
    () =>
      loading ? (
        <Loader2 className="h-5 w-5 animate-spin" />
      ) : (
        <RefreshCw className="h-5 w-5" />
      ),
    [loading]
  );

  useEffect(() => {
    if (localSearchTerm !== searchTerm) {
      setSearching(true);
      const debounceTimer = window.setTimeout(() => {
        onSearchChange(localSearchTerm);
        setSearching(false);
      }, SEARCH_DEBOUNCE);

      return () => {
        window.clearTimeout(debounceTimer);
        setSearching(false);
      };
    }

    return undefined;
  }, [localSearchTerm, searchTerm, onSearchChange]);

  useEffect(() => {
    setLocalSearchTerm(searchTerm);
  }, [searchTerm]);

  const inputPadding = localSearchTerm ? "pr-12" : "pr-10";

  return (
    <TooltipProvider>
      <header className="sticky top-0 z-50 border-b border-slate-200 bg-white transition-colors dark:border-slate-800 dark:bg-slate-900">
        <div className="min-h-16 relative flex flex-col items-center justify-between gap-4 px-4 py-2 sm:px-6 md:flex-row">
          <div className="flex w-full items-center gap-4 md:w-auto">
            <button
              onClick={onToggleSidebar}
              className="-ml-2 rounded-md p-2 text-slate-600 transition hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:text-slate-300 dark:hover:bg-slate-800 dark:focus-visible:ring-offset-slate-900 md:hidden"
              aria-label="Open navigation sidebar"
              type="button"
            >
              <Menu className="h-6 w-6" />
            </button>
            <button
              onClick={onGoHome}
              className="group flex items-center gap-3 text-xl font-bold text-slate-800 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:text-slate-200 dark:focus-visible:ring-offset-slate-900"
              type="button"
            >
              <Logo
                className={`h-10 w-10 text-slate-600 transition-all duration-300 ease-in-out group-hover:rotate-[30deg] dark:text-slate-300 ${
                  loading ? "animate-spin" : ""
                }`}
              />
              <span className="tracking-tighter">Harmony</span>
            </button>
          </div>

          <div className="flex w-full flex-wrap items-center justify-center gap-x-4 gap-y-2 md:w-auto md:justify-end">
            <div className="relative w-full md:w-auto">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                {searchIcon}
              </div>
              <Input
                type="text"
                placeholder="Search tracks, artists, albums..."
                aria-label="Search tracks, artists and albums"
                className={`w-full max-w-[36rem] rounded-lg border-gray-300 pl-10 text-sm focus:ring-2 focus:ring-indigo-500 focus:ring-offset-0 dark:border-gray-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-offset-slate-900 ${inputPadding}`}
                value={localSearchTerm}
                onChange={(event) => setLocalSearchTerm(event.target.value)}
              />
              {localSearchTerm && (
                <div className="absolute inset-y-0 right-0 flex items-center space-x-2 pr-3">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        onClick={() => {
                          setLocalSearchTerm("");
                          onSearchChange("");
                        }}
                        className="text-gray-400 transition hover:text-gray-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:text-gray-500 dark:hover:text-gray-400 dark:focus-visible:ring-offset-slate-900"
                        aria-label="Clear search input"
                        type="button"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>Clear search</TooltipContent>
                  </Tooltip>
                </div>
              )}
            </div>

            <div className="flex items-center space-x-2">
              {filterButtons.map((filter) => (
                <Tooltip key={filter.key}>
                  <TooltipTrigger asChild>
                    <button
                      onClick={filter.onClick}
                      className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900 ${
                        filter.isActive
                          ? filter.activeClass
                          : "bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
                      }`}
                      aria-pressed={filter.isActive}
                      type="button"
                    >
                      {filter.label}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>{filter.title}</TooltipContent>
                </Tooltip>
              ))}
            </div>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onRefresh}
                  disabled={loading}
                  className="hover:bg-gray-100 dark:hover:bg-gray-800"
                  aria-label="Refresh data"
                  type="button"
                >
                  {refreshIcon}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {loading ? "Refreshing..." : "Refresh all data"}
              </TooltipContent>
            </Tooltip>

            {onShowWhatsNew && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={onShowWhatsNew}
                    className={`relative hover:bg-gray-100 dark:hover:bg-gray-800 ${
                      hasNewFeatures
                        ? "text-indigo-600 dark:text-indigo-400 animate-pulse"
                        : ""
                    }`}
                    aria-label={
                      hasNewFeatures
                        ? "Open what's new panel"
                        : "Show latest updates"
                    }
                    type="button"
                  >
                    <Sparkles className="h-5 w-5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {hasNewFeatures ? "See what's new!" : "What's new"}
                </TooltipContent>
              </Tooltip>
            )}

            {onShowNotifications && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={onShowNotifications}
                    className="hover:bg-gray-100 dark:hover:bg-gray-800"
                    aria-label="Benachrichtigungen anzeigen"
                    type="button"
                  >
                    <Bell className="h-5 w-5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Benachrichtigungen</TooltipContent>
              </Tooltip>
            )}

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onThemeToggle}
                  className="hover:bg-gray-100 dark:hover:bg-gray-800"
                  aria-label={
                    isDarkMode ? "Switch to light mode" : "Switch to dark mode"
                  }
                  type="button"
                >
                  {isDarkMode ? (
                    <Sun className="h-5 w-5" />
                  ) : (
                    <Moon className="h-5 w-5" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {isDarkMode ? "Switch to light mode" : "Switch to dark mode"}
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </header>
    </TooltipProvider>
  );
};

export type { AppHeaderProps, ServiceFilters };
export default AppHeader;
