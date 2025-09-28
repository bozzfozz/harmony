import { Suspense, lazy, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';

import { Tabs, TabsContent } from '../../components/ui/shadcn';
import LibraryTabs, { LibraryTabKey, libraryTabItems } from './LibraryTabs';

const LibraryArtists = lazy(() => import('./LibraryArtists'));
const LibraryDownloads = lazy(() => import('./LibraryDownloads'));
const LibraryWatchlist = lazy(() => import('./LibraryWatchlist'));

const DEFAULT_TAB: LibraryTabKey = 'artists';

const isLibraryTab = (value: string | null): value is LibraryTabKey =>
  libraryTabItems.some((tab) => tab.value === value);

const LibraryPage = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get('tab');
  const activeTab = useMemo<LibraryTabKey>(() => {
    if (isLibraryTab(rawTab)) {
      return rawTab;
    }
    if (typeof rawTab === 'string' && isLibraryTab(rawTab.toLowerCase())) {
      return rawTab.toLowerCase() as LibraryTabKey;
    }
    return DEFAULT_TAB;
  }, [rawTab]);

  useEffect(() => {
    if (!isLibraryTab(rawTab)) {
      const next = new URLSearchParams(searchParams);
      next.set('tab', activeTab);
      setSearchParams(next, { replace: true });
    }
  }, [activeTab, rawTab, searchParams, setSearchParams]);

  const handleTabChange = (nextTab: string) => {
    const normalized = isLibraryTab(nextTab) ? nextTab : DEFAULT_TAB;
    const params = new URLSearchParams(searchParams);
    params.set('tab', normalized);
    setSearchParams(params);
  };

  const renderTabFallback = () => (
    <div className="flex justify-center py-12 text-muted-foreground">
      <span className="inline-flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Lädt Inhalte…
      </span>
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">Library</h1>
        <p className="text-sm text-muted-foreground">
          Verwalten Sie Artists, Downloads und Ihre Watchlist an einem Ort.
        </p>
      </div>
      <Tabs value={activeTab} onValueChange={handleTabChange} className="space-y-6">
        <LibraryTabs />
        <TabsContent value="artists" className="space-y-6">
          {activeTab === 'artists' ? (
            <Suspense fallback={renderTabFallback()}>
              <LibraryArtists isActive />
            </Suspense>
          ) : null}
        </TabsContent>
        <TabsContent value="downloads" className="space-y-6">
          {activeTab === 'downloads' ? (
            <Suspense fallback={renderTabFallback()}>
              <LibraryDownloads isActive />
            </Suspense>
          ) : null}
        </TabsContent>
        <TabsContent value="watchlist" className="space-y-6">
          {activeTab === 'watchlist' ? (
            <Suspense fallback={renderTabFallback()}>
              <LibraryWatchlist isActive />
            </Suspense>
          ) : null}
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default LibraryPage;
