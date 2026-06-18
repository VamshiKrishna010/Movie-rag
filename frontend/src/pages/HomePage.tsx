import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  browseMovies,
  searchMovies,
  type Movie,
  type PaginatedMovies,
  type SearchResponse,
  PAGE_SIZE,
} from "../api/movies";
import { ContentShell } from "../components/ContentShell";
import { MovieGrid } from "../components/MovieGrid";
import { Pagination } from "../components/Pagination";
import { useGenre } from "../context/GenreContext";
import { useSearch } from "../context/SearchContext";
import {
  browseCacheKey,
  getCache,
  searchCacheKey,
  setCache,
} from "../lib/cache";

function readPage(params: URLSearchParams): number {
  const n = Number.parseInt(params.get("page") ?? "1", 10);
  return Number.isFinite(n) && n > 0 ? n : 1;
}

export default function HomePage() {
  const { genreId, selectedGenreName } = useGenre();
  const { debouncedQuery, resetPageRef } = useSearch();
  const [searchParams, setSearchParams] = useSearchParams();
  const page = readPage(searchParams);

  const setPage = useCallback(
    (next: number) => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (next <= 1) params.delete("page");
          else params.set("page", String(next));
          return params;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );
  const [movies, setMovies] = useState<Movie[]>([]);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [searchMode, setSearchMode] = useState<"title" | "hybrid" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const prevGenreRef = useRef(genreId);

  useEffect(() => {
    resetPageRef.current = () => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          params.delete("page");
          return params;
        },
        { replace: true },
      );
    };
    return () => {
      resetPageRef.current = null;
    };
  }, [resetPageRef, setSearchParams]);

  useEffect(() => {
    if (prevGenreRef.current !== genreId) {
      prevGenreRef.current = genreId;
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          params.delete("page");
          return params;
        },
        { replace: true },
      );
    }
  }, [genreId, setSearchParams]);

  useEffect(() => {
    let cancelled = false;

    async function loadMovies() {
      await Promise.resolve();
      if (cancelled) return;

      const cacheKey = debouncedQuery
        ? searchCacheKey(debouncedQuery, genreId, page)
        : browseCacheKey(genreId, page);

      const cached = getCache<PaginatedMovies | SearchResponse>(cacheKey);
      if (cached) {
        setMovies(cached.movies);
        setTotalPages(cached.total_pages);
        setSearchMode(
          debouncedQuery && "mode" in cached ? cached.mode : null,
        );
        setError(null);
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);

      try {
        if (debouncedQuery) {
          const data = await searchMovies(debouncedQuery, {
            page,
            limit: PAGE_SIZE,
            genreId,
          });
          if (cancelled) return;
          setCache(cacheKey, data);
          setMovies(data.movies);
          setTotalPages(data.total_pages);
          setSearchMode(data.mode);
        } else {
          const data = await browseMovies({ page, limit: PAGE_SIZE, genreId });
          if (cancelled) return;
          setCache(cacheKey, data);
          setMovies(data.movies);
          setTotalPages(data.total_pages);
          setSearchMode(null);
        }
      } catch (err) {
        if (cancelled) return;
        setMovies([]);
        setTotalPages(1);
        setSearchMode(null);
        const message =
          err instanceof Error ? err.message : "Something went wrong";
        setError(
          debouncedQuery
            ? message
            : "Failed to load movies. Check that the API and database are running.",
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadMovies();
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery, genreId, page]);

  const handlePageChange = (nextPage: number) => {
    setPage(nextPage);
    contentRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <ContentShell>
      <div ref={contentRef}>
        {(genreId !== null || (searchMode && debouncedQuery && !loading)) && (
          <p className="mb-4 text-xs text-muted">
            {genreId !== null && <span>{selectedGenreName}</span>}
            {genreId !== null && searchMode && debouncedQuery && !loading && " · "}
            {searchMode && debouncedQuery && !loading && (
              <span>{searchMode === "hybrid" ? "Semantic search" : "Title search"}</span>
            )}
          </p>
        )}

        <MovieGrid
          movies={movies}
          loading={loading}
          emptyMessage={error ?? "No movies found"}
        />

        <Pagination
          page={page}
          totalPages={totalPages}
          onChange={handlePageChange}
        />
      </div>
    </ContentShell>
  );
}
