import { TabsList, TabsTrigger } from '../../components/ui/shadcn';

export const libraryTabItems = [
  { value: 'artists', label: 'Artists' },
  { value: 'downloads', label: 'Downloads' },
  { value: 'watchlist', label: 'Watchlist' }
] as const;

export type LibraryTabKey = (typeof libraryTabItems)[number]['value'];

const LibraryTabs = () => (
  <TabsList className="grid w-full max-w-sm grid-cols-3">
    {libraryTabItems.map((tab) => (
      <TabsTrigger key={tab.value} value={tab.value} className="capitalize">
        {tab.label}
      </TabsTrigger>
    ))}
  </TabsList>
);

export default LibraryTabs;
