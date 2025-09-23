import { createContext, useContext } from "react";

type SearchContextValue = {
  term: string;
  setTerm: (term: string) => void;
};

const SearchContext = createContext<SearchContextValue | undefined>(undefined);

const SearchProvider = SearchContext.Provider;

const useGlobalSearch = () => {
  const context = useContext(SearchContext);
  if (!context) {
    throw new Error("useGlobalSearch must be used within a SearchProvider");
  }
  return context;
};

export { SearchContext, SearchProvider, useGlobalSearch };
