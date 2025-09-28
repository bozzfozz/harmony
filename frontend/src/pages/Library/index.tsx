import { useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

import { Tabs, TabsContent } from '../../components/ui/shadcn';
import LibraryArtists from './LibraryArtists';
import LibraryDownloads from './LibraryDownloads';
import LibraryTabs, { LibraryTabKey, libraryTabItems } from './LibraryTabs';
import LibraryWatchlist from './LibraryWatchlist';

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
    setSearchParams(params, { replace: true });
  };

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
          <LibraryArtists />
        </TabsContent>
        <TabsContent value="downloads" className="space-y-6">
          <LibraryDownloads />
        </TabsContent>
        <TabsContent value="watchlist" className="space-y-6">
          <LibraryWatchlist />
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default LibraryPage;
