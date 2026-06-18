import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

const DEBOUNCE_MS = 300;

interface SearchContextValue {
  query: string;
  setQuery: (q: string) => void;
  debouncedQuery: string;
  submitSearch: () => void;
  resetPageRef: React.MutableRefObject<(() => void) | null>;
}

const SearchContext = createContext<SearchContextValue | null>(null);

export function SearchProvider({ children }: { children: ReactNode }) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const resetPageRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const delay = query.trim() ? DEBOUNCE_MS : 0;
    debounceRef.current = setTimeout(() => {
      setDebouncedQuery(query.trim());
      resetPageRef.current?.();
    }, delay);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  const submitSearch = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setDebouncedQuery(query.trim());
    resetPageRef.current?.();
  }, [query]);

  return (
    <SearchContext.Provider
      value={{ query, setQuery, debouncedQuery, submitSearch, resetPageRef }}
    >
      {children}
    </SearchContext.Provider>
  );
}

export function useSearch() {
  const ctx = useContext(SearchContext);
  if (!ctx) throw new Error("useSearch must be used within SearchProvider");
  return ctx;
}
