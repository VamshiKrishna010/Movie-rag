import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { fetchGenres, type Genre } from "../api/movies";
import { getStoredGenreId, setStoredGenreId } from "../lib/cookies";

interface GenreContextValue {
  genres: Genre[];
  genreId: number | null;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  selectGenre: (id: number | null) => void;
  selectedGenreName: string;
}

const GenreContext = createContext<GenreContextValue | null>(null);

export function GenreProvider({ children }: { children: ReactNode }) {
  const [genres, setGenres] = useState<Genre[]>([]);
  const [genreId, setGenreId] = useState<number | null>(() => getStoredGenreId());
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    fetchGenres()
      .then(setGenres)
      .catch(() => {});
  }, []);

  const selectGenre = useCallback((id: number | null) => {
    setGenreId(id);
    setStoredGenreId(id);
    setSidebarOpen(false);
  }, []);

  const selectedGenreName =
    genreId === null
      ? "All genres"
      : (genres.find((g) => g.id === genreId)?.name ?? "All genres");

  return (
    <GenreContext.Provider
      value={{
        genres,
        genreId,
        sidebarOpen,
        setSidebarOpen,
        selectGenre,
        selectedGenreName,
      }}
    >
      {children}
    </GenreContext.Provider>
  );
}

export function useGenre() {
  const ctx = useContext(GenreContext);
  if (!ctx) throw new Error("useGenre must be used within GenreProvider");
  return ctx;
}
