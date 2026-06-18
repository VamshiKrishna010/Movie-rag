import { Link } from "react-router-dom";
import type { Movie } from "../api/movies";

interface MovieCardProps {
  movie: Movie;
}

function FilmIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-10 w-10 text-muted">
      <path d="M4.5 4.5a3 3 0 00-3 3v9a3 3 0 003 3h8.25a3 3 0 003-3v-9a3 3 0 00-3-3H4.5zM19.94 18.75l-2.69-2.69V7.94l2.69-2.69c.944-.945 2.56-.276 2.56 1.06v11.38c0 1.336-1.616 2.005-2.56 1.06z" />
    </svg>
  );
}

export function MovieCard({ movie }: MovieCardProps) {
  const rating =
    movie.vote_average != null ? movie.vote_average.toFixed(1) : null;

  return (
    <article className="group">
      <Link
        to={`/movie/${movie.id}`}
        className="block"
        aria-label={`View details for ${movie.title}`}
      >
        <div className="relative aspect-[2/3] overflow-hidden rounded-xl bg-skeleton transition-transform duration-200 group-hover:scale-[1.02]">
          {movie.poster_url ? (
            <img
              src={movie.poster_url}
              alt={movie.title}
              loading="lazy"
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center bg-surface">
              <FilmIcon />
            </div>
          )}
        </div>
        <h3 className="mt-2 truncate text-sm font-medium text-text">
          {movie.title}
        </h3>
        <p className="text-xs text-muted">
          {movie.release_year ?? "—"}
          {rating && ` · ★ ${rating}`}
        </p>
      </Link>
    </article>
  );
}

function SkeletonCard() {
  return (
    <div>
      <div className="aspect-[2/3] rounded-xl bg-skeleton skeleton-pulse" />
      <div className="mt-2 h-4 w-3/4 rounded bg-skeleton skeleton-pulse" />
      <div className="mt-1.5 h-3 w-1/2 rounded bg-skeleton skeleton-pulse" />
    </div>
  );
}

interface MovieGridProps {
  movies: Movie[];
  loading: boolean;
  emptyMessage?: string;
}

export function MovieGrid({
  movies,
  loading,
  emptyMessage = "No movies found",
}: MovieGridProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {Array.from({ length: 16 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    );
  }

  if (movies.length === 0) {
    return (
      <p className="py-16 text-center text-muted">{emptyMessage}</p>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {movies.map((movie) => (
        <MovieCard key={movie.id} movie={movie} />
      ))}
    </div>
  );
}
